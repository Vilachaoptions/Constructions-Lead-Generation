"""Browser session: launch Chromium and persist/reuse the logged-in state.

The authenticated cookies are saved to ``<session-dir>/storage_state.json`` so
subsequent runs reuse the session without logging in again (and without storing
the password anywhere on disk).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..logging_setup import get_logger

STORAGE_FILE = "storage_state.json"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def storage_state_path(settings: Settings) -> Path:
    return settings.session_dir / STORAGE_FILE


def launch_context(playwright, settings: Settings):
    """Launch Chromium and return ``(browser, context)``.

    Loads a saved storage state if one exists. Caller is responsible for closing
    both the context and the browser.
    """
    log = get_logger()
    launch_kwargs = {"headless": not settings.headful}
    # Allow pointing at a system-provided Chromium (e.g. preinstalled in CI /
    # sandboxes) instead of the pip-managed download.
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if exe and os.path.exists(exe):
        launch_kwargs["executable_path"] = exe
        log.info("Using Chromium at %s", exe)
    browser = playwright.chromium.launch(**launch_kwargs)

    state_path = storage_state_path(settings)
    kwargs = {"user_agent": _USER_AGENT}
    if state_path.exists():
        log.info("Reusing saved session at %s", state_path)
        kwargs["storage_state"] = str(state_path)

    context = browser.new_context(**kwargs)
    return browser, context


def save_state(context, settings: Settings) -> Path:
    """Persist the context's cookies/localStorage to the session dir."""
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    path = storage_state_path(settings)
    context.storage_state(path=str(path))
    get_logger().info("Saved session to %s", path)
    return path
