"""Extract a lesson's notes (the rich-text lesson body) and render to Markdown.

Skool stores lesson notes in the lesson's ``metadata`` under one of a few keys.
The value is usually an HTML string; occasionally a structured rich-text doc.
We normalize either form to Markdown, preserving links and images.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from markdownify import markdownify as _md

# metadata keys that have been observed to hold lesson notes, most-specific first
_NOTE_KEYS = (
    "descriptionHtml",
    "contentHtml",
    "description",
    "desc",
    "content",
    "body",
    "notes",
    "text",
)

# A heuristic: does this string look like HTML markup?
def _looks_like_html(value: str) -> bool:
    v = value.lstrip()
    return v.startswith("<") and ">" in v


def _raw_notes_field(metadata: dict) -> Optional[Any]:
    for key in _NOTE_KEYS:
        val = metadata.get(key)
        if val:
            return val
    return None


def html_to_markdown(html: str) -> str:
    md = _md(html, heading_style="ATX", strip=["script", "style"])
    # collapse 3+ blank lines that markdownify can leave behind
    lines = [ln.rstrip() for ln in md.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        if ln == "":
            blanks += 1
            if blanks <= 2:
                out.append(ln)
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out).strip()


def _render_richtext(node: Any) -> str:
    """Minimal renderer for structured rich-text docs (best-effort).

    Handles the common node shapes (paragraph/heading/list/link/text). Unknown
    node types fall through to their child text so nothing is silently dropped.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_render_richtext(n) for n in node)
    if not isinstance(node, dict):
        return ""

    ntype = node.get("type")
    children = node.get("children", node.get("content", []))
    inner = _render_richtext(children)

    if ntype in (None, "text"):
        return node.get("text", inner)
    if ntype in ("paragraph", "p"):
        return inner + "\n\n"
    if ntype in ("heading", "h"):
        level = int(node.get("level", node.get("depth", 2)) or 2)
        return "#" * max(1, min(level, 6)) + " " + inner.strip() + "\n\n"
    if ntype in ("link", "a"):
        href = node.get("url") or node.get("href") or ""
        return f"[{inner}]({href})"
    if ntype in ("list-item", "li"):
        return f"- {inner.strip()}\n"
    if ntype in ("bulleted-list", "ul", "numbered-list", "ol"):
        return inner + "\n"
    if ntype in ("image", "img"):
        src = node.get("url") or node.get("src") or ""
        return f"![]({src})\n\n"
    return inner


def _render_resources(metadata: dict) -> Optional[str]:
    """Render a lesson's ``resources`` (links/files) into a Markdown list."""
    raw = metadata.get("resources")
    if not raw:
        return None
    items = raw
    if isinstance(raw, str):
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(items, list) or not items:
        return None

    lines = ["**Resources**", ""]
    found = False
    for it in items:
        if not isinstance(it, dict):
            continue
        title = it.get("title") or it.get("file_name") or it.get("name") or "resource"
        link = it.get("link") or it.get("url")
        if link:
            lines.append(f"- [{title}]({link})")
        elif it.get("file_name"):
            lines.append(f"- {title} (file: {it.get('file_name')})")
        else:
            lines.append(f"- {title}")
        found = True
    return "\n".join(lines) if found else None


def _description_markdown(raw) -> tuple[Optional[str], Optional[str]]:
    """Convert a description field (HTML / rich-text / plain) to ``(html, md)``."""
    if isinstance(raw, str) and raw.lstrip().startswith(("[", "{")):
        try:
            md = _render_richtext(json.loads(raw)).strip()
            if md:
                return raw, md
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(raw, (list, dict)):
        md = _render_richtext(raw).strip()
        return None, (md or None)
    if isinstance(raw, str):
        if _looks_like_html(raw):
            return raw, html_to_markdown(raw)
        return None, (raw.strip() or None)
    return None, None


def extract_notes(lesson_raw: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """Return ``(notes_html, notes_markdown)`` for a lesson's raw JSON node.

    Combines the lesson's text description (if any) with a rendered list of its
    attached resources. Either element may be None if the lesson has neither.
    """
    if not isinstance(lesson_raw, dict):
        return None, None
    metadata = lesson_raw.get("metadata")
    if not isinstance(metadata, dict):
        return None, None

    desc_html, desc_md = _description_markdown(_raw_notes_field(metadata))
    resources_md = _render_resources(metadata)

    parts = [p for p in (desc_md, resources_md) if p]
    notes_md = "\n\n".join(parts) if parts else None
    return desc_html, notes_md
