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


def _looks_like_course_node(node: Any) -> bool:
    """A course/module/lesson node: a dict with an id and a metadata dict."""
    return (
        isinstance(node, dict)
        and "id" in node
        and isinstance(node.get("metadata"), dict)
    )


def find_course_root(data: dict[str, Any], course_id: Optional[str] = None) -> dict[str, Any]:
    """Locate the root course node within the __NEXT_DATA__ payload.

    Strategy:
      1. If ``course_id`` is given, find the node whose ``id`` matches and which
         has children (i.e. the course container, not a leaf reference).
      2. Otherwise pick the course-like node with the most descendant nodes,
         which is almost always the top-level course container.

    Raises NextDataError if no suitable node is found.
    """
    candidates = [n for n in walk(data, _looks_like_course_node)]
    if not candidates:
        raise NextDataError(
            "No course/lesson nodes found in __NEXT_DATA__. Are you authorized to "
            "view this classroom, and is the URL a classroom (not a feed) page?"
        )

    def has_children(node: dict) -> bool:
        return bool(node.get("children"))

    if course_id:
        for node in candidates:
            if str(node.get("id")) == str(course_id) and has_children(node):
                return node
        # fall back to id match even without children
        for node in candidates:
            if str(node.get("id")) == str(course_id):
                return node

    # Otherwise: the container with the most descendant course-like nodes.
    containers = [n for n in candidates if has_children(n)]
    pool = containers or candidates
    return max(pool, key=lambda n: sum(1 for _ in walk(n, _looks_like_course_node)))
