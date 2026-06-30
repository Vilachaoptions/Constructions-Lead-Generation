"""Debug helper: summarize the shape of a Skool __NEXT_DATA__ payload.

Used by ``--debug-structure`` to locate where the course/module/lesson tree
actually lives in the page data, so the parser can be adapted to Skool's current
schema. Prints a compact, paste-friendly report and dumps the raw JSON to disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _title_of(item: dict) -> str:
    md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for v in (md.get("title"), md.get("name"), item.get("name"), item.get("title")):
        if isinstance(v, str) and v.strip():
            return v.strip()[:60]
    return "?"


def summarize(data: dict[str, Any]) -> str:
    lines: list[str] = []

    pp = data.get("props", {})
    pp = pp.get("pageProps", {}) if isinstance(pp, dict) else {}
    if isinstance(pp, dict):
        lines.append("props.pageProps keys: " + ", ".join(sorted(map(str, pp.keys()))))
        lines.append("")

    # Collect candidate arrays: lists of dicts that carry an `id`.
    seen: dict[str, dict] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            dict_items = [x for x in node if isinstance(x, dict)]
            if dict_items and any("id" in x for x in dict_items):
                rec = seen.setdefault(path, {"count": 0, "sample_keys": None,
                                             "has_children": False, "titles": [],
                                             "types": set()})
                rec["count"] += len(dict_items)
                if rec["sample_keys"] is None:
                    rec["sample_keys"] = sorted(map(str, dict_items[0].keys()))[:16]
                for it in dict_items:
                    if it.get("children"):
                        rec["has_children"] = True
                    t = it.get("type") or (it.get("metadata", {}) or {}).get("type")
                    if t:
                        rec["types"].add(str(t))
                    if len(rec["titles"]) < 5:
                        rec["titles"].append(_title_of(it))
            for x in node:
                walk(x, f"{path}[]")

    walk(data, "")

    lines.append(f"Found {len(seen)} candidate array location(s) of dicts-with-id:")
    lines.append("")
    for path, rec in sorted(seen.items(), key=lambda kv: -kv[1]["count"])[:40]:
        types = ",".join(sorted(rec["types"])) or "-"
        lines.append(f"PATH {path or '<root>'}")
        lines.append(f"   count={rec['count']}  has_children={rec['has_children']}  types={types}")
        lines.append(f"   item_keys={rec['sample_keys']}")
        lines.append(f"   sample_titles={rec['titles']}")
        lines.append("")

    return "\n".join(lines)


def _trim(obj: Any, depth: int, max_str: int, max_list: int) -> Any:
    """Return a depth/size-limited copy of ``obj`` for safe, compact previewing."""
    if depth <= 0:
        if isinstance(obj, dict):
            return {"<keys>": sorted(map(str, obj.keys()))}
        if isinstance(obj, list):
            return f"<list len={len(obj)}>"
        return obj
    if isinstance(obj, dict):
        return {k: _trim(v, depth - 1, max_str, max_list) for k, v in obj.items()}
    if isinstance(obj, list):
        trimmed = [_trim(x, depth - 1, max_str, max_list) for x in obj[:max_list]]
        if len(obj) > max_list:
            trimmed.append(f"<+{len(obj) - max_list} more, total {len(obj)}>")
        return trimmed
    if isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str] + f"…<+{len(obj) - max_str} chars>"
    return obj


def preview_keys(data: dict[str, Any], keys: list[str],
                 depth: int = 6, max_str: int = 120, max_list: int = 3) -> str:
    """Print a trimmed JSON skeleton of selected props.pageProps.<key> objects."""
    pp = data.get("props", {})
    pp = pp.get("pageProps", {}) if isinstance(pp, dict) else {}
    out: list[str] = []
    for key in keys:
        out.append(f"===== props.pageProps.{key} =====")
        if key not in pp:
            out.append("  <absent>")
            continue
        trimmed = _trim(pp[key], depth, max_str, max_list)
        out.append(json.dumps(trimmed, indent=2, ensure_ascii=False))
        out.append("")
    return "\n".join(out)


def dump_raw(data: dict[str, Any], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return dest
