"""Email + password login to Skool via Playwright.

Lazy: only runs when the current session isn't already authenticated. Detects
2FA / captcha challenge screens and raises a clear, actionable error rather than
attempting to bypass them.
"""

from __future__ import annotations

from ..config import Settings
from ..logging_setup import get_logger
from . import session as session_mod

LOGIN_URL = "https://www.skool.com/login"


class LoginError(Exception):
    """Login failed (bad credentials, network, or unexpected page)."""


class ChallengeError(LoginError):
    """A 2FA / captcha / verification challenge blocked headless login."""


def is_logged_in(page) -> bool:
    """Cheap probe: navigate to the account page and check we weren't bounced.

    Skool redirects unauthenticated users to /login, so if we still land on an
    authenticated URL we're logged in.
    """
    try:
        page.goto("https://www.skool.com/settings", wait_until="domcontentloaded",
                  timeout=30000)
    except Exception:  # pragma: no cover - network flake
        return False
    return "/login" not in page.url and "/settings" in page.url


def _detect_challenge(page) -> bool:
    content = page.content().lower()
    markers = ("verification code", "two-factor", "2fa", "captcha",
               "recaptcha", "verify it's you", "verify your identity")
    return any(m in content for m in markers)


def login(context, settings: Settings) -> None:
    """Perform email/password login and persist the session.

    Raises Config/LoginError variants on failure.
    """
    log = get_logger()
    if not settings.skool_email or not settings.skool_password:
        raise LoginError(
            "No saved session and no credentials. Set SKOOL_EMAIL and "
            "SKOOL_PASSWORD in your .env file."
        )

    page = context.new_page()
    if is_logged_in(page):
        log.info("Already authenticated; reusing session.")
        page.close()
        return

    log.info("Logging in to Skool as %s", settings.skool_email)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)

    try:
        page.fill("input[type=email], input[name=email]", settings.skool_email, timeout=20000)
        page.fill("input[type=password], input[name=password]", settings.skool_password,
                  timeout=20000)
        page.click("button[type=submit]", timeout=20000)
    except Exception as exc:  # pragma: no cover - markup change
        raise LoginError(
            f"Could not find/fill the login form ({exc}). Skool may have changed "
            "its login page; try --headful to log in manually."
        ) from exc

    # Wait for either a redirect away from /login or a challenge to appear.
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
    except Exception:
        if _detect_challenge(page):
            raise ChallengeError(
                "Login hit a 2FA / verification challenge. Re-run once with "
                "--headful and complete the challenge in the browser window; the "
                "session will then be saved for future headless runs."
            )
        raise LoginError(
            "Login did not complete. Check your credentials, or re-run with "
            "--headful to see what happened."
        )

    if "/login" in page.url:
        raise LoginError("Still on the login page after submit — credentials likely incorrect.")

    session_mod.save_state(context, settings)
    page.close()
    log.info("Login successful.")
