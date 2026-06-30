"""Kajabi course adapter (e.g. Define Digital Academy).

Reuses the saved ``webcourse discover`` session, parses the Kajabi sidebar into a
course tree, and for each lesson extracts the post body (notes) and the Wistia
video, then runs the same transcript pipeline + Markdown/master output as the
Skool extractor.

Kajabi shape (from discovery):
  * Sidebar modules:   <h3 class="product-outline-category"> (+ -subcategory)
  * Lessons:           <a href=".../categories/<cat>/posts/<post>">
  * Lesson title:      <h1 class="post-body-title">
  * Video:             Wistia (wistia_async_<id> / wistia.com/embed/medias/<id>)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from skool_extractor.config import Settings
from skool_extractor.logging_setup import emit, get_logger, setup_logging
from skool_extractor.models import (STATUS_DONE, STATUS_ERROR, STATUS_PARTIAL,
                                    STATUS_SKIPPED, Course, Lesson, Module,
                                    Transcript, VideoRef)
from skool_extractor.output import manifest as manifest_mod
from skool_extractor.output import markdown_writer
from skool_extractor.output.state import StateStore, notes_hash
from skool_extractor.parse.notes import html_to_markdown
from skool_extractor.parse.tree_builder import slugify
from skool_extractor.transcript import pipeline as transcript_pipeline
from skool_extractor.video import cookies as cookies_mod

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_POST_RE = re.compile(r"/categories/\d+/posts/(\d+)")
_WISTIA_RE = re.compile(
    r"wistia_async_([a-z0-9]+)|wistia\.(?:com|net)/(?:embed/)?(?:iframe|medias)/([a-z0-9]+)",
    re.IGNORECASE,
)
_FILE_EXT_RE = re.compile(
    r"\.(pdf|zip|xlsx?|csv|docx?|pptx?|txt|json|png|jpe?g|gif|mp3|mp4|mov|key|numbers|pages)(\?|#|$)",
    re.IGNORECASE,
)


def _is_download(a) -> bool:
    href = a.get("href", "")
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return False
    if a.has_attr("download"):
        return True
    if _FILE_EXT_RE.search(href):
        return True
    return any(s in href for s in (
        "kajabi-cdn.com", "amazonaws.com", "/downloads/", "/attachments/",
        "/download", "cloudfront.net"))


def _find_resources(soup, base_url: str) -> list[dict]:
    """Collect downloadable file links (PDFs, sheets, guides) from a lesson."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        if not _is_download(a):
            continue
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True) or a.get("download") or "download"
        out.append({"title": re.sub(r"\s+", " ", title)[:120], "url": url})
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_title(text: str) -> str:
    """Strip the SVG icon label Kajabi prepends ('… Created with Sketch.')."""
    if "Created with Sketch." in text:
        text = text.split("Created with Sketch.", 1)[1]
    return re.sub(r"\s+", " ", text).strip()


def _settings(args, host: str, slug: str) -> Settings:
    return Settings(
        classroom_url=args.url,
        community=host,
        course_id=slug,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        session_dir=Path(args.session_dir).expanduser().resolve(),
        transcription_backend=args.transcription_backend,
        whisper_model=args.whisper_model,
        use_captions=not args.no_captions,
        transcripts_enabled=not args.no_transcripts,
        timestamps=args.timestamps,
        force=args.force,
        only_lesson=args.only,
    )


def build_course(html: str, host: str, slug: str, url: str) -> Course:
    soup = BeautifulSoup(html, "lxml")
    dash = soup.find(class_="mini-dashboard-title")
    title = dash.get_text(strip=True) if dash else slug
    course = Course(id=slug, community=host, title=title, slug=slug, url=url)

    current_module: Module | None = None
    current_sub: str | None = None
    seen: set[str] = set()

    for el in soup.find_all(["h3", "a"]):
        classes = el.get("class") or []
        if el.name == "h3" and "product-outline-category" in classes:
            name = el.get_text(" ", strip=True)
            current_module = Module(id=slugify(name) or f"m{len(course.modules)}",
                                    title=name, order=len(course.modules))
            course.modules.append(current_module)
            current_sub = None
        elif el.name == "h3" and "product-outline-subcategory" in classes:
            current_sub = el.get_text(" ", strip=True)
        elif el.name == "a":
            m = _POST_RE.search(el.get("href", ""))
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            if current_module is None:
                current_module = Module(id="root", title=title, order=0)
                course.modules.append(current_module)
            path = [current_module.title] + ([current_sub] if current_sub else [])
            course_url = f"https://{host}{el['href']}"
            current_module.lessons.append(Lesson(
                id=m.group(1),
                title=_clean_title(el.get_text(" ", strip=True)) or f"Lesson {m.group(1)}",
                order=len(current_module.lessons),
                module_path=path,
                url=course_url,
            ))
    return course


def parse_lesson(html: str, base_url: str = "") -> tuple:
    """Return ``(title, notes_markdown, wistia_id, resources)`` for a lesson page."""
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find(class_="post-body-title")
    title = title_el.get_text(strip=True) if title_el else None

    body = None
    for sel in (".post-body", ".kjb-content", ".formatted-content",
                ".mighty-post-content", ".post-content"):
        body = soup.select_one(sel)
        if body:
            break
    if body is None and title_el is not None:
        body = title_el.parent

    notes_md = None
    if body is not None:
        for junk in body.select(
                ".post-body-title, script, style, [class*=wistia], [class*=video], "
                ".mark-complete, .post-completion"):
            junk.decompose()
        notes_md = html_to_markdown(str(body)) or None
        if notes_md:
            # Drop lines that are only separators (---, ***, ___) and treat a
            # body with no actual words as empty (common on video-only lessons).
            cleaned = "\n".join(
                ln for ln in notes_md.splitlines()
                if not re.fullmatch(r"\s*[-*_]{2,}\s*", ln)
            ).strip()
            notes_md = cleaned if re.search(r"[A-Za-z0-9]", cleaned) else None

    wid = None
    m = _WISTIA_RE.search(html)
    if m:
        wid = m.group(1) or m.group(2)

    resources = _find_resources(soup, base_url)
    return title, notes_md, wid, resources


def _safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("/", "-")
    name = re.sub(r'[<>:"\\|?*\x00-\x1f]', "", name)
    return name[:120] or "download"


def _download_resources(context, resources: list[dict], dest_dir: Path,
                        log) -> list[dict]:
    """Download each resource into ``dest_dir`` using the authenticated session.

    Returns the list with a local ``filename`` added for those that downloaded.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for res in resources:
        try:
            resp = context.request.get(res["url"], timeout=120000)
            if not resp.ok:
                log.warning("Download failed (%s): %s", resp.status, res["url"])
                continue
            cd = resp.headers.get("content-disposition", "")
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
            if m:
                fname = _safe_filename(m.group(1))
            else:
                path_name = urlparse(res["url"]).path.rsplit("/", 1)[-1]
                fname = _safe_filename(path_name) if "." in path_name \
                    else _safe_filename(res["title"])
            (dest_dir / fname).write_bytes(resp.body())
            res["filename"] = fname
            log.info("Downloaded resource: %s", fname)
        except Exception as exc:  # noqa: BLE001
            log.warning("Download error for %s: %s", res["url"], exc)
    return resources


def _append_resource_links(notes_md, resources: list[dict]):
    lines = []
    for r in resources:
        if r.get("filename"):
            lines.append(f"- [{r['title']}](_files/{r['filename']})")
        else:
            lines.append(f"- [{r['title']}]({r['url']})")
    if not lines:
        return notes_md
    block = "**Downloads**\n\n" + "\n".join(lines)
    return f"{notes_md}\n\n{block}" if notes_md else block


def run_kajabi(args) -> int:
    from playwright.sync_api import sync_playwright

    log = setup_logging(verbose=getattr(args, "verbose", False))
    parts = urlparse(args.url)
    host = parts.netloc or "site"
    slug_m = re.search(r"/products/([^/?#]+)", args.url)
    slug = slug_m.group(1) if slug_m else "course"
    settings = _settings(args, host, slug)
    started = _now_iso()

    state_path = settings.session_dir / "storage_state.json"
    if not state_path.exists():
        log.error("No saved session at %s. Run `webcourse discover <url>` first to log in.",
                  state_path)
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT,
                                      storage_state=str(state_path))
        page = context.new_page()
        try:
            log.info("Fetching course: %s", args.url)
            emit("fetch_classroom", url=args.url)
            page.goto(args.url, wait_until="networkidle", timeout=60000)
            course = build_course(page.content(), host, slug, args.url)
            log.info("Parsed course '%s' with %d lessons", course.title, course.lesson_count())
            emit("course_parsed", title=course.title, lessons=course.lesson_count())

            cookie_file = cookies_mod.write_cookie_file(
                state_path, settings.session_dir / "cookies.txt")
            state = StateStore(settings.output_dir, course)
            manifest_mod.write_manifest(settings.output_dir, course, settings, started)
            media_dir = markdown_writer.course_dir(settings.output_dir, course) / "_media"

            lessons = list(course.iter_lessons())
            if settings.only_lesson:
                lessons = [l for l in lessons if l.id == settings.only_lesson]
            total = len(lessons)
            errors = 0

            for index, lesson in enumerate(lessons, start=1):
                emit("lesson_start", index=index, total=total, id=lesson.id, title=lesson.title)
                if state.should_skip(lesson, settings.force):
                    lesson.status = STATUS_SKIPPED
                    emit("lesson_skip", id=lesson.id, title=lesson.title)
                    continue
                try:
                    page.goto(lesson.url, wait_until="networkidle", timeout=60000)
                    _, notes_md, wid, resources = parse_lesson(page.content(), lesson.url)
                    if resources and getattr(args, "download_resources", False):
                        base = markdown_writer.course_dir(settings.output_dir, course)
                        files_dir = markdown_writer._module_dir(base, lesson) / "_files"
                        _download_resources(context, resources, files_dir, log)
                    if resources:
                        notes_md = _append_resource_links(notes_md, resources)
                    lesson.notes_markdown = notes_md
                    if wid:
                        lesson.video = VideoRef(provider="wistia",
                                                url=f"https://fast.wistia.com/medias/{wid}",
                                                provider_id=wid, raw=wid)
                    lesson.transcript = transcript_pipeline.get_transcript(
                        lesson.video, settings, media_dir, cookie_file)
                    markdown_writer.write_lesson(settings.output_dir, course, lesson,
                                                 timestamps=settings.timestamps)
                    lesson.notes_hash = notes_hash(lesson.notes_markdown)
                    lesson.extracted_at = _now_iso()
                    lesson.status = (STATUS_PARTIAL if lesson.transcript and
                                     lesson.transcript.error else STATUS_DONE)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    lesson.status = STATUS_ERROR
                    log.exception("Lesson failed: %s", lesson.title)
                    emit("lesson_error", id=lesson.id, error=str(exc))

                state.mark(lesson)
                manifest_mod.write_manifest(settings.output_dir, course, settings, started)
                emit("lesson_done", index=index, total=total, id=lesson.id,
                     status=lesson.status,
                     transcript=lesson.transcript.source if lesson.transcript else None)

            master = markdown_writer.write_master(settings.output_dir, course)
            log.info("Wrote master document: %s", master)
            emit("master_written", path=str(master))
            done = sum(1 for l in lessons if l.status == STATUS_DONE)
            skipped = sum(1 for l in lessons if l.status == STATUS_SKIPPED)
            emit("run_complete", total=total, done=done, skipped=skipped, errors=errors)
            log.info("Done: %d extracted, %d skipped, %d errors. Output: %s",
                     done, skipped, errors,
                     markdown_writer.course_dir(settings.output_dir, course))
            return 2 if errors else 0
        finally:
            context.close()
            browser.close()
