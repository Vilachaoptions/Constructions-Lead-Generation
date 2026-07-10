"""Public Notion site extractor.

Walks a **public** ``*.notion.site`` page via Notion's unofficial public API
(no login needed), following every child page and database (collection) row,
and writes:

  * one Markdown file per page/template under ``pages/``
  * a ``databases/<name>.csv`` + ``.json`` for every collection (the "database")
  * a ``MASTER.md`` index of the whole tree

Design notes
------------
Notion renders lazily and virtualizes long lists, so scraping the DOM misses
most rows. Instead we call the same JSON API the web app uses:

  * ``/api/v3/loadPageChunk``   -> a page's block tree (recordMap)
  * ``/api/v3/queryCollection`` -> every row id of a database view

A block's ``space_id`` (needed by queryCollection) comes straight from the
loadPageChunk recordMap, so no auth/token is required for public sites.

Use ``--debug`` to also dump the raw API JSON under ``_raw/`` — if a page
renders wrong, send those files back for diagnosis.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from skool_extractor.logging_setup import emit, get_logger, setup_logging
from skool_extractor.parse.tree_builder import slugify

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HEX32 = re.compile(r"([0-9a-fA-F]{32})")
_UUID = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def dash_id(raw: str) -> str:
    """Normalize a 32-hex or dashed Notion id to canonical dashed UUID form."""
    raw = raw.strip()
    m = _UUID.search(raw)
    if m:
        return m.group(1).lower()
    m = _HEX32.search(raw.replace("-", ""))
    if not m:
        return raw.lower()
    h = m.group(1).lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def page_id_from_url(url: str) -> str:
    """Extract the trailing page id from a Notion URL/slug."""
    # strip query/hash, take last path segment
    path = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    return dash_id(tail)


def site_base(url: str) -> str:
    m = re.match(r"(https?://[^/]+)", url)
    return m.group(1) if m else "https://www.notion.so"


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #
class NotionClient:
    def __init__(self, base: str, log, debug_dir: Optional[Path] = None,
                 pause: float = 0.2):
        self.base = base.rstrip("/")
        self.log = log
        self.debug_dir = debug_dir
        self.pause = pause
        self._n = 0

    def _post(self, endpoint: str, body: dict) -> dict:
        url = f"{self.base}/api/v3/{endpoint}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
            "Accept": "application/json",
            "notion-audit-log-platform": "web",
        })
        last_exc = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode("utf-8")
                out = json.loads(raw)
                if self.debug_dir:
                    self._n += 1
                    (self.debug_dir / f"{self._n:04d}_{endpoint}.json").write_text(
                        raw, encoding="utf-8")
                if self.pause:
                    time.sleep(self.pause)
                return out
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in (429, 502, 503):
                    time.sleep(2 ** attempt)
                    continue
                body_txt = exc.read().decode("utf-8", "replace")[:300]
                self.log.warning("%s -> HTTP %s: %s", endpoint, exc.code, body_txt)
                raise
            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{endpoint} failed after retries: {last_exc}")

    def load_page(self, page_id: str) -> dict:
        """Return the merged recordMap for a page (all chunks)."""
        record: dict[str, dict] = {}
        cursor = {"stack": []}
        chunk = 0
        while True:
            out = self._post("loadPageChunk", {
                "pageId": page_id,
                "limit": 100,
                "cursor": cursor,
                "chunkNumber": chunk,
                "verticalColumns": False,
            })
            rm = out.get("recordMap", {})
            for table, entries in rm.items():
                record.setdefault(table, {}).update(entries)
            cursor = out.get("cursor", {}) or {"stack": []}
            if not cursor.get("stack"):
                break
            chunk += 1
        return record

    def query_collection(self, collection_id: str, view_id: str,
                         space_id: str) -> tuple[list[str], dict]:
        """Return (row_block_ids, recordMap) for every row of a collection view."""
        # Current signature (source/collectionView/loader.reducers).
        bodies = [
            {
                "source": {"type": "collection", "id": collection_id,
                           "spaceId": space_id},
                "collectionView": {"id": view_id, "spaceId": space_id},
                "loader": {
                    "reducers": {"collection_group_results": {
                        "type": "results", "limit": 5000}},
                    "sortAndAggregationVersions": {},
                    "searchQuery": "",
                    "userTimeZone": "UTC",
                },
            },
            # Legacy signature (collection/collectionView/loader.type=reducer).
            {
                "collection": {"id": collection_id, "spaceId": space_id},
                "collectionView": {"id": view_id, "spaceId": space_id},
                "loader": {
                    "type": "reducer",
                    "reducers": {"collection_group_results": {
                        "type": "results", "limit": 5000}},
                    "searchQuery": "",
                    "userTimeZone": "UTC",
                },
            },
        ]
        for body in bodies:
            try:
                out = self._post("queryCollection", body)
            except urllib.error.HTTPError:
                continue
            rm = out.get("recordMap", {})
            ids = _extract_block_ids(out.get("result", {}))
            if ids or rm.get("block"):
                if not ids:
                    ids = list(rm.get("block", {}).keys())
                return ids, rm
        return [], {}


def _extract_block_ids(result: dict) -> list[str]:
    if not isinstance(result, dict):
        return []
    if result.get("blockIds"):
        return result["blockIds"]
    rr = result.get("reducerResults", {})
    cg = rr.get("collection_group_results", {}) if isinstance(rr, dict) else {}
    if cg.get("blockIds"):
        return cg["blockIds"]
    # grouped results
    ids: list[str] = []
    for v in (rr.values() if isinstance(rr, dict) else []):
        if isinstance(v, dict) and v.get("blockIds"):
            ids.extend(v["blockIds"])
    return ids


# --------------------------------------------------------------------------- #
# Rich text + block rendering
# --------------------------------------------------------------------------- #
def render_rich(segments: Any, ctx: "Ctx") -> str:
    """Render Notion rich-text (array of ``[text, [marks...]]``) to Markdown."""
    if not isinstance(segments, list):
        return ""
    out = []
    for seg in segments:
        if not isinstance(seg, list) or not seg:
            continue
        text = seg[0] if isinstance(seg[0], str) else ""
        marks = seg[1] if len(seg) > 1 and isinstance(seg[1], list) else []
        link = None
        page_ref = None
        for mk in marks:
            if not isinstance(mk, list) or not mk:
                continue
            kind = mk[0]
            if kind == "a" and len(mk) > 1:
                link = mk[1]
            elif kind == "p" and len(mk) > 1:      # inline page mention
                page_ref = dash_id(mk[1])
            elif kind == "b":
                text = f"**{text}**"
            elif kind == "i":
                text = f"_{text}_"
            elif kind == "c":
                text = f"`{text}`"
            elif kind == "s":
                text = f"~~{text}~~"
        if page_ref:
            ctx.enqueue(page_ref)
            title = ctx.title_for(page_ref) or "Untitled"
            out.append(f"[{title}](./{ctx.file_for(page_ref)})")
            continue
        if link:
            full = ctx.resolve_link(link)
            out.append(f"[{text or full}]({full})")
        else:
            out.append(text)
    return "".join(out)


_HEADINGS = {"header": "# ", "sub_header": "## ", "sub_sub_header": "### "}
_PAGEISH = {"page", "collection_view_page"}


def render_block(bid: str, record: dict, ctx: "Ctx", depth: int = 0,
                 index: int = 1) -> list[str]:
    block = record.get("block", {}).get(bid, {})
    val = block.get("value") if isinstance(block, dict) else None
    if not val:
        return []
    btype = val.get("type", "")
    props = val.get("properties", {}) or {}
    title = props.get("title", [])
    pad = "  " * depth
    lines: list[str] = []

    def kids():
        for cid in val.get("content", []) or []:
            lines.extend(render_block(cid, record, ctx, depth, 1))

    if btype in _PAGEISH:
        ctx.enqueue(bid)
        t = render_rich(title, ctx) or ctx.title_for(bid) or "Untitled"
        lines.append(f"{pad}- [{t}](./{ctx.file_for(bid)})")
        return lines
    if btype == "collection_view":
        lines.extend(ctx.render_collection(val))
        return lines
    if btype in _HEADINGS:
        lines.append(f"{_HEADINGS[btype]}{render_rich(title, ctx)}")
    elif btype == "text":
        txt = render_rich(title, ctx)
        lines.append(f"{pad}{txt}" if txt else "")
    elif btype == "bulleted_list":
        lines.append(f"{pad}- {render_rich(title, ctx)}")
        _render_children_indented(val, record, ctx, depth, lines)
        return lines
    elif btype == "numbered_list":
        lines.append(f"{pad}{index}. {render_rich(title, ctx)}")
        _render_children_indented(val, record, ctx, depth, lines)
        return lines
    elif btype == "to_do":
        checked = props.get("checked", [["No"]])[0][0] == "Yes"
        box = "x" if checked else " "
        lines.append(f"{pad}- [{box}] {render_rich(title, ctx)}")
    elif btype == "toggle":
        lines.append(f"{pad}**{render_rich(title, ctx)}**")
        _render_children_indented(val, record, ctx, depth, lines)
        return lines
    elif btype == "quote":
        lines.append(f"{pad}> {render_rich(title, ctx)}")
    elif btype == "callout":
        icon = (val.get("format", {}) or {}).get("page_icon", "")
        lines.append(f"{pad}> {icon} {render_rich(title, ctx)}".rstrip())
    elif btype == "code":
        lang = render_rich(props.get("language", [["text"]]), ctx).lower() or ""
        lines.append(f"```{lang}\n{_plain(title)}\n```")
    elif btype == "divider":
        lines.append("---")
    elif btype in ("image", "embed", "video", "file", "pdf"):
        src = ctx.media_source(val)
        cap = render_rich(title, ctx)
        if btype == "image":
            lines.append(f"![{cap}]({src})")
        else:
            lines.append(f"[{cap or btype}]({src})")
    elif btype == "bookmark":
        link = (val.get("format", {}) or {}).get("bookmark_url") \
            or _plain(props.get("link", []))
        lines.append(f"[{render_rich(title, ctx) or link}]({ctx.resolve_link(link)})")
    elif btype in ("column_list", "column"):
        kids()
        return lines
    else:
        # Unknown block: still surface its text if any.
        txt = render_rich(title, ctx)
        if txt:
            lines.append(f"{pad}{txt}")

    kids()
    return lines


def _render_children_indented(val, record, ctx, depth, lines):
    n = 1
    for cid in val.get("content", []) or []:
        child = render_block(cid, record, ctx, depth + 1, n)
        lines.extend(child)
        n += 1


def _plain(segments: Any) -> str:
    if not isinstance(segments, list):
        return ""
    return "".join(s[0] for s in segments
                   if isinstance(s, list) and s and isinstance(s[0], str))


# --------------------------------------------------------------------------- #
# Extraction context / orchestration
# --------------------------------------------------------------------------- #
class Ctx:
    def __init__(self, client: NotionClient, base: str, out_dir: Path, log,
                 max_pages: int):
        self.client = client
        self.base = base
        self.out_dir = out_dir
        self.log = log
        self.max_pages = max_pages
        self.records: dict[str, dict] = {}     # page_id -> recordMap
        self.titles: dict[str, str] = {}       # id -> title
        self.files: dict[str, str] = {}        # id -> pages/<slug>.md
        self.queue: list[str] = []
        self.done: set[str] = set()
        self.databases: list[dict] = []        # collected DB exports (for index)
        self._current_record: dict = {}

    # -- id helpers -------------------------------------------------------- #
    def enqueue(self, pid: str):
        pid = dash_id(pid)
        if pid not in self.done and pid not in self.queue:
            self.queue.append(pid)

    def file_for(self, pid: str) -> str:
        pid = dash_id(pid)
        if pid not in self.files:
            slug = slugify(self.titles.get(pid, "")) or pid[:8]
            fname = f"pages/{slug}-{pid[:8]}.md"
            self.files[pid] = fname
        return self.files[pid]

    def title_for(self, pid: str) -> str:
        return self.titles.get(dash_id(pid), "")

    def resolve_link(self, link: str) -> str:
        if not link:
            return ""
        if link.startswith("/"):
            return f"{self.base}{link}"
        return link

    def media_source(self, val: dict) -> str:
        props = val.get("properties", {}) or {}
        fmt = val.get("format", {}) or {}
        src = fmt.get("display_source") or _plain(props.get("source", []))
        if src and "amazonaws.com" in src and "secure.notion" not in src:
            # Public file proxy for S3-hosted assets.
            from urllib.parse import quote
            return f"{self.base}/image/{quote(src, safe='')}"
        return src

    # -- collection / database rendering ---------------------------------- #
    def render_collection(self, view_val: dict) -> list[str]:
        record = self._current_record
        coll_id = view_val.get("collection_id") \
            or (view_val.get("format", {}) or {}).get("collection_pointer", {}).get("id")
        view_ids = view_val.get("view_ids", []) or [view_val.get("id")]
        space_id = view_val.get("space_id", "")
        if not coll_id:
            return ["", "_[embedded database]_", ""]
        coll = record.get("collection", {}).get(coll_id, {}).get("value", {})
        if not coll:
            # collection record may live only in the query response; fetch it.
            pass
        name = _plain(coll.get("name", [])) or "database"
        schema = coll.get("schema", {}) or {}

        row_ids, rm = self.client.query_collection(coll_id, view_ids[0], space_id)
        # merge collection/block records from the query response
        for table, entries in rm.items():
            self._current_record.setdefault(table, {}).update(entries)
            self.records_merge(table, entries)
        if not coll:
            coll = self._current_record.get("collection", {}).get(
                coll_id, {}).get("value", {})
            name = _plain(coll.get("name", [])) or name
            schema = coll.get("schema", {}) or schema

        rows = self.export_database(name, coll_id, schema, row_ids, view_val)
        # Enqueue each row page for full content extraction.
        for rid in row_ids:
            self.enqueue(rid)
        rel = f"../databases/{slugify(name)}.csv"
        lines = ["", f"**Database: {name}** ({len(row_ids)} rows) -> "
                 f"[`{slugify(name)}.csv`]({rel})", ""]
        for r in rows[:50]:
            t = r.get("__title__", "Untitled")
            pid = r.get("__id__", "")
            lines.append(f"- [{t}](../{self.file_for(pid)})")
        if len(rows) > 50:
            lines.append(f"- … {len(rows) - 50} more (see CSV)")
        lines.append("")
        return lines

    def records_merge(self, table: str, entries: dict):
        # keep a global copy so row pages can be titled even before loaded
        for bid, rec in entries.items():
            if table == "block":
                val = rec.get("value", {}) if isinstance(rec, dict) else {}
                t = _plain((val.get("properties", {}) or {}).get("title", []))
                if t:
                    self.titles.setdefault(dash_id(bid), t)

    def export_database(self, name: str, coll_id: str, schema: dict,
                        row_ids: list[str], view_val: dict) -> list[dict]:
        record = self._current_record
        # Column order: prefer the view's table_properties, else schema order.
        order = []
        tp = (view_val.get("format", {}) or {}).get("table_properties", [])
        for entry in tp:
            cid = entry.get("property")
            if cid in schema and entry.get("visible", True):
                order.append(cid)
        for cid in schema:
            if cid not in order:
                order.append(cid)
        col_names = {cid: schema[cid].get("name", cid) for cid in order}
        title_cid = next((c for c in schema if schema[c].get("type") == "title"),
                         "title")

        rows: list[dict] = []
        for rid in row_ids:
            rid = dash_id(rid)
            blk = record.get("block", {}).get(rid, {}).get("value", {})
            props = blk.get("properties", {}) or {}
            title = _plain(props.get(title_cid, [])) or self.titles.get(rid, "Untitled")
            self.titles[rid] = title
            row = {"__id__": rid, "__title__": title,
                   "page_file": self.file_for(rid)}
            for cid in order:
                row[col_names[cid]] = _plain(props.get(cid, []))
            rows.append(row)

        # Write CSV + JSON
        db_dir = self.out_dir / "databases"
        db_dir.mkdir(parents=True, exist_ok=True)
        slug = slugify(name) or coll_id[:8]
        headers = ["__title__"] + [col_names[c] for c in order] + \
                  ["notion_page_id", "page_file"]
        with (db_dir / f"{slug}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            for r in rows:
                w.writerow([r.get("__title__", "")] +
                           [r.get(col_names[c], "") for c in order] +
                           [r.get("__id__", ""), r.get("page_file", "")])
        (db_dir / f"{slug}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.databases.append({"name": name, "slug": slug, "rows": len(rows)})
        self.log.info("Database '%s': %d rows -> databases/%s.csv",
                      name, len(rows), slug)
        emit("notion_database", name=name, rows=len(rows))
        return rows

    # -- page extraction --------------------------------------------------- #
    def extract_page(self, pid: str):
        pid = dash_id(pid)
        record = self.client.load_page(pid)
        self._current_record = record
        block = record.get("block", {}).get(pid, {}).get("value", {})
        title = _plain((block.get("properties", {}) or {}).get("title", [])) \
            or self.titles.get(pid, "") or "Untitled"
        self.titles[pid] = title
        fname = self.file_for(pid)

        body: list[str] = [f"# {title}", ""]
        for cid in block.get("content", []) or []:
            body.extend(render_block(cid, record, self, 0, 1))

        path = self.out_dir / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(body).rstrip() + "\n"
        text = re.sub(r"\n{3,}", "\n\n", text)
        path.write_text(text, encoding="utf-8")
        self.log.info("Page: %s -> %s", title, fname)
        emit("notion_page", title=title, file=fname)


def run_notion(args) -> int:
    log = setup_logging(verbose=getattr(args, "verbose", False))
    base = site_base(args.url)
    root_id = page_id_from_url(args.url)
    out_dir = Path(args.output_dir).expanduser().resolve() / f"notion__{root_id[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = None
    if getattr(args, "debug", False):
        debug_dir = out_dir / "_raw"
        debug_dir.mkdir(parents=True, exist_ok=True)

    log.info("Notion site: %s (root %s)", base, root_id)
    emit("notion_start", url=args.url, root=root_id)
    client = NotionClient(base, log, debug_dir=debug_dir,
                          pause=getattr(args, "pause", 0.2))
    ctx = Ctx(client, base, out_dir, log, max_pages=getattr(args, "max_pages", 2000))
    ctx.enqueue(root_id)

    count = 0
    while ctx.queue:
        pid = ctx.queue.pop(0)
        if pid in ctx.done:
            continue
        if count >= ctx.max_pages:
            log.warning("Reached --max-pages=%d; %d pages still queued (skipped).",
                        ctx.max_pages, len(ctx.queue))
            break
        ctx.done.add(pid)
        try:
            ctx.extract_page(pid)
            count += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Page %s failed: %s", pid, exc)
        emit("notion_progress", done=count, queued=len(ctx.queue))

    _write_master(ctx, root_id)
    log.info("Done: %d pages, %d databases. Output: %s",
             count, len(ctx.databases), out_dir)
    emit("notion_complete", pages=count, databases=len(ctx.databases),
         output=str(out_dir))
    return 0


def _write_master(ctx: Ctx, root_id: str):
    lines = [f"# {ctx.titles.get(root_id, 'Notion Export')}", "",
             f"_Extracted {len(ctx.done)} pages, {len(ctx.databases)} databases._", ""]
    if ctx.databases:
        lines.append("## Databases")
        for db in ctx.databases:
            lines.append(f"- **{db['name']}** — {db['rows']} rows "
                         f"([`databases/{db['slug']}.csv`](databases/{db['slug']}.csv))")
        lines.append("")
    lines.append("## Pages")
    for pid in ctx.done:
        title = ctx.titles.get(pid, "Untitled")
        fname = ctx.files.get(pid)
        if fname:
            lines.append(f"- [{title}]({fname})")
    (ctx.out_dir / "MASTER.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.log.info("Wrote master index: %s", ctx.out_dir / "MASTER.md")
