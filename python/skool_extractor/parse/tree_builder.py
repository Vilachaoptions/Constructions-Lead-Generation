"""Build a typed Course -> Module -> Lesson tree from Skool's course payload.

Skool's ``props.pageProps.course`` is a nested wrapper tree::

    { "course": <node>, "children": [ { "course": <node>, "children": [...] }, ... ] }

Each ``<node>`` carries a ``metadata`` dict and a ``unitType``:
  * ``course`` — the root course node
  * ``set``    — a section / folder that groups lessons (and/or nested sets)
  * ``module`` — an actual lesson (carries ``videoLink``, ``resources``, ``title``)

We map: Skool ``set`` -> our ``Module`` (a section), Skool ``module`` -> our
``Lesson``. Lessons that sit directly under the course (not inside a set) are
grouped into an implicit top-level section and written at the course root.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from ..models import Course, Lesson, Module


def _inner(wrapper: dict) -> Optional[dict]:
    """The node carried by a wrapper ``{"course": <node>, ...}``."""
    node = wrapper.get("course") if isinstance(wrapper, dict) else None
    return node if isinstance(node, dict) else None


def _meta(node: dict) -> dict:
    meta = node.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _title(node: dict, fallback: str = "Untitled") -> str:
    meta = _meta(node)
    for val in (meta.get("title"), meta.get("name"), node.get("name")):
        if isinstance(val, str) and val.strip():
            return val.strip()
    return fallback


def _child_wrappers(wrapper: dict) -> list[dict]:
    kids = wrapper.get("children") if isinstance(wrapper, dict) else None
    if not isinstance(kids, list):
        return []
    return [w for w in kids if isinstance(w, dict) and isinstance(w.get("course"), dict)]


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (slug[:max_len].strip("-")) or "untitled"


def _lesson_url(classroom_url: str, lesson_id: str) -> str:
    if not classroom_url:
        return ""
    parts = urlparse(classroom_url)
    query = parse_qs(parts.query)
    query["md"] = [lesson_id]
    new_query = urlencode({k: v[0] for k, v in query.items()})
    return urlunparse(parts._replace(query=new_query))


def build_course(wrapper: dict, community: str, course_id: str,
                 classroom_url: str = "") -> Course:
    """Construct the full Course tree from ``props.pageProps.course``."""
    root = _inner(wrapper) or {}
    title = _title(root, "Course")
    course = Course(
        id=str(root.get("id") or course_id),
        community=community,
        title=title,
        slug=root.get("name") or slugify(title),
        url=classroom_url,
        raw=wrapper,
    )

    implicit: Optional[Module] = None

    def ensure_implicit() -> Module:
        nonlocal implicit
        if implicit is None:
            implicit = Module(id=course.id + "__top", title="", order=-1, parent_id=None)
            course.modules.insert(0, implicit)
        return implicit

    def process(children: list[dict], parent: Optional[Module], path: list[str]) -> None:
        for idx, w in enumerate(children):
            node = _inner(w)
            if node is None:
                continue
            unit = str(node.get("unitType") or "").lower()
            name = _title(node, f"Item {idx + 1}")

            if unit == "module":  # a lesson
                target = parent if parent is not None else ensure_implicit()
                lesson = Lesson(
                    id=str(node.get("id")),
                    title=name,
                    order=idx,
                    module_path=list(path),     # [] when top-level -> written at root
                    url=_lesson_url(classroom_url, str(node.get("id"))),
                    raw=node,
                )
                target.lessons.append(lesson)
            else:  # "set" / "course" / unknown -> a section (Module)
                module = Module(
                    id=str(node.get("id")),
                    title=name,
                    order=idx,
                    parent_id=parent.id if parent else course.id,
                )
                if parent is None:
                    course.modules.append(module)
                else:
                    parent.submodules.append(module)
                process(_child_wrappers(w), module, path + [name])

    process(_child_wrappers(wrapper), None, [])
    return course
