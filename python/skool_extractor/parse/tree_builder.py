"""Build a typed Course -> Module -> Lesson tree from Skool's course node.

Skool nests content as a tree of nodes that each carry a ``metadata`` dict and an
optional ``children`` list. Container nodes (with children) become Modules; leaf
nodes become Lessons. Field names are normalized here so the rest of the codebase
works against ``models.py`` and never touches raw Skool JSON.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..models import Course, Lesson, Module


def _meta(node: dict) -> dict:
    meta = node.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _title(node: dict, fallback: str = "Untitled") -> str:
    meta = _meta(node)
    for key in ("title", "name"):
        val = meta.get(key) or node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return fallback


def _children(node: dict) -> list[dict]:
    kids = node.get("children")
    if isinstance(kids, list):
        return [k for k in kids if isinstance(k, dict)]
    return []


def _order(node: dict, index: int) -> int:
    """Best-effort sort order; fall back to discovery index."""
    meta = _meta(node)
    for key in ("order", "position", "rank", "index"):
        val = meta.get(key)
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str) and val.strip().lstrip("-").isdigit():
            return int(val)
    return index


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (slug[:max_len].strip("-")) or "untitled"


def _is_container(node: dict) -> bool:
    """A node is a module/container iff it has child nodes."""
    return len(_children(node)) > 0


def _build_module(node: dict, index: int, parent_path: list[str],
                  parent_id: Optional[str]) -> Module:
    title = _title(node, fallback=f"Module {index + 1}")
    module = Module(
        id=str(node.get("id")),
        title=title,
        order=_order(node, index),
        parent_id=parent_id,
    )
    here_path = parent_path + [title]
    children = sorted(enumerate(_children(node)), key=lambda p: _order(p[1], p[0]))
    for child_index, child in children:
        if _is_container(child):
            module.submodules.append(
                _build_module(child, child_index, here_path, module.id)
            )
        else:
            module.lessons.append(
                _build_lesson(child, child_index, here_path)
            )
    return module


def _build_lesson(node: dict, index: int, module_path: list[str]) -> Lesson:
    return Lesson(
        id=str(node.get("id")),
        title=_title(node, fallback=f"Lesson {index + 1}"),
        order=_order(node, index),
        module_path=list(module_path),
        raw=node,
    )


def build_course(root: dict, community: str, course_id: str,
                 classroom_url: str = "") -> Course:
    """Construct the full Course tree from the located course root node."""
    title = _title(root, fallback="Course")
    course = Course(
        id=str(root.get("id") or course_id),
        community=community,
        title=title,
        slug=slugify(_meta(root).get("name") or root.get("name") or title),
        url=classroom_url,
        raw=root,
    )

    top = sorted(enumerate(_children(root)), key=lambda p: _order(p[1], p[0]))
    for index, child in top:
        if _is_container(child):
            course.modules.append(_build_module(child, index, [], course.id))
        else:
            # A flat course with no module grouping: wrap leaf lessons in a
            # single implicit module so the output layout stays uniform.
            if not course.modules or course.modules[-1].id != course.id:
                course.modules.append(
                    Module(id=course.id, title=title, order=0, parent_id=None)
                )
            course.modules[-1].lessons.append(
                _build_lesson(child, index, [title])
            )
    return course
