"""Navigate Skool classroom/lesson pages and return their HTML.

Centralizes politeness: a small randomized delay between navigations and retry
with exponential backoff on transient navigation failures.
"""

from __future__ import annotations

import random
import time
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import Settings
from ..logging_setup import get_logger


class PageFetcher:
    def __init__(self, context, settings: Settings):
        self._context = context
        self._settings = settings
        self._page = context.new_page()
        self._log = get_logger()
        self._last_nav = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_nav
        wait = self._settings.min_delay + random.uniform(0, self._settings.jitter)
        if elapsed < wait:
            time.sleep(wait - elapsed)

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=2, min=2, max=16),
           reraise=True)
    def _goto(self, url: str) -> str:
        self._throttle()
        self._page.goto(url, wait_until="networkidle", timeout=60000)
        self._last_nav = time.monotonic()
        return self._page.content()

    def fetch_classroom(self, url: str) -> str:
        self._log.info("Fetching classroom: %s", url)
        return self._goto(url)

    def fetch_lesson(self, classroom_url: str, lesson_id: str) -> str:
        """Navigate to the lesson deep-link (``?md=<lesson-id>``) and return HTML."""
        url = _with_md_param(classroom_url, lesson_id)
        self._log.info("Fetching lesson %s", lesson_id)
        return self._goto(url)

    def close(self) -> None:
        try:
            self._page.close()
        except Exception:  # pragma: no cover
            pass


def _with_md_param(url: str, lesson_id: str) -> str:
    parts = urlparse(url)
    query = parse_qs(parts.query)
    query["md"] = [lesson_id]
    new_query = urlencode({k: v[0] for k, v in query.items()})
    return urlunparse(parts._replace(query=new_query))
