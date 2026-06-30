"""Extract and search Skool's ``__NEXT_DATA__`` JSON payload.

Skool is a Next.js app: the page ships a ``<script id="__NEXT_DATA__">`` tag
containing the fully-hydrated props, including the classroom's course tree. We
parse that JSON rather than scraping rendered DOM.

Everything here is shape-tolerant: we locate nodes by the *shape* of their keys
(an ``id`` plus a ``metadata`` dict, optionally with ``children``) rather than by
fixed JSON paths, so minor Skool schema changes don't break extraction.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterator, Optional

from bs4 import BeautifulSoup


class NextDataError(Exception):
    """Raised when __NEXT_DATA__ cannot be found or parsed."""


def extract_next_data(html: str) -> dict[str, Any]:
    """Return the parsed ``__NEXT_DATA__`` JSON object from a page's HTML."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        raise NextDataError(
            "No <script id='__NEXT_DATA__'> found. The page may not have loaded, "
            "you may not be logged in, or Skool changed its markup."
        )
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise NextDataError(f"__NEXT_DATA__ was not valid JSON: {exc}") from exc


def walk(obj: Any, predicate: Callable[[Any], bool]) -> Iterator[Any]:
    """Recursively yield every node (dict/list/scalar) for which ``predicate`` is True.

    Descends into both dicts and lists. Yields matching nodes in document order.
    """
    if predicate(obj):
        yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk(value, predicate)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item, predicate)


def extract_course_wrapper(data: dict[str, Any]) -> dict[str, Any]:
    """Locate ``props.pageProps.course`` — Skool's nested course wrapper.

    The wrapper has the shape ``{"course": <root-node>, "children": [...]}`` where
    the root node's ``unitType`` is ``course``. Falls back to searching the whole
    payload for such a wrapper.
    """
    pp = data.get("props", {})
    pp = pp.get("pageProps", {}) if isinstance(pp, dict) else {}
    wrapper = pp.get("course") if isinstance(pp, dict) else None
    if isinstance(wrapper, dict) and isinstance(wrapper.get("course"), dict):
        return wrapper

    for node in walk(data, lambda n: isinstance(n, dict)
                     and isinstance(n.get("course"), dict)
                     and str(n["course"].get("unitType", "")).lower() == "course"):
        return node

    raise NextDataError(
        "Could not find the course wrapper (props.pageProps.course) in __NEXT_DATA__. "
        "Are you authorized to view this classroom, and is the URL a classroom page?"
    )


