"""Extract a lesson's notes (the rich-text lesson body) and render to Markdown.

Skool stores lesson notes in the lesson's ``metadata`` under one of a few keys.
The value is usually an HTML string; occasionally a structured rich-text doc.
We normalize either form to Markdown, preserving links and images.
"""

from __future__ import annotations

import json
import re
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


def _apply_marks(text: str, marks: Any) -> str:
    """Wrap inline text with Markdown for its ProseMirror marks (link/bold/...)."""
    if not isinstance(marks, list):
        return text
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mtype = mark.get("type")
        attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
        if mtype == "link":
            href = attrs.get("href") or attrs.get("url") or ""
            if href:
                text = f"[{text}]({href})"
        elif mtype in ("bold", "strong"):
            text = f"**{text}**"
        elif mtype in ("italic", "em"):
            text = f"*{text}*"
        elif mtype == "code":
            text = f"`{text}`"
        elif mtype in ("strike", "strikethrough"):
            text = f"~~{text}~~"
    return text


def _render_richtext(node: Any) -> str:
    """Render a ProseMirror/TipTap-style rich-text doc (Skool's ``desc``) to Markdown.

    Handles paragraphs, headings, bullet/ordered lists, links, inline marks,
    blockquotes, code blocks and hard breaks. Unknown node types fall through to
    their child text so nothing is silently dropped.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_render_richtext(n) for n in node)
    if not isinstance(node, dict):
        return ""

    ntype = node.get("type")
    content = node.get("content", node.get("children", []))

    if ntype in (None, "text"):
        return _apply_marks(node.get("text", ""), node.get("marks"))

    inner = _render_richtext(content)

    if ntype in ("paragraph", "p"):
        return inner + "\n\n"
    if ntype in ("heading", "h"):
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        level = int(attrs.get("level", node.get("level", 2)) or 2)
        return "#" * max(1, min(level, 6)) + " " + inner.strip() + "\n\n"
    if ntype in ("link", "a"):
        href = node.get("url") or node.get("href") or ""
        return f"[{inner}]({href})"
    if ntype in ("listItem", "list_item", "list-item", "li"):
        return f"- {inner.strip()}\n"
    if ntype in ("bulletList", "bullet_list", "bulleted-list", "ul",
                 "orderedList", "ordered_list", "numbered-list", "ol"):
        return inner + "\n"
    if ntype in ("blockquote",):
        return "> " + inner.strip() + "\n\n"
    if ntype in ("codeBlock", "code_block"):
        return "```\n" + inner.strip() + "\n```\n\n"
    if ntype in ("hardBreak", "hard_break", "br"):
        return "\n"
    if ntype in ("image", "img"):
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        src = attrs.get("src") or node.get("url") or node.get("src") or ""
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


# Skool prefixes rich-text descriptions with a version tag, e.g. "[v2][{...}]".
_RICHTEXT_PREFIX = re.compile(r"^\[v\d+\]")


def _description_markdown(raw) -> tuple[Optional[str], Optional[str]]:
    """Convert a description field (Skool rich-text / HTML / plain) to ``(html, md)``."""
    if isinstance(raw, str):
        candidate = raw.strip()
        prefix = _RICHTEXT_PREFIX.match(candidate)
        if prefix:
            candidate = candidate[prefix.end():].lstrip()
        if candidate.startswith(("[", "{")):
            try:
                md = _render_richtext(json.loads(candidate)).strip()
                if md:
                    return None, md
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
