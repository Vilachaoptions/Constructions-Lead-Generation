"""Command-line entrypoint and end-to-end orchestration.

Drives: login -> fetch classroom -> parse course tree -> per-lesson notes +
transcript -> write Markdown + manifest. Emits newline-delimited JSON progress
events on stdout for the Node wrapper; human logs go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__
from .config import ConfigError, Settings, build_settings
from .logging_setup import emit, get_logger, setup_logging
from .models import (STATUS_DONE, STATUS_ERROR, STATUS_PARTIAL, STATUS_SKIPPED,
                     Course, Lesson)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skool-extractor",
        description="Extract a Skool.com classroom's lessons, notes, and transcripts.",
    )
    p.add_argument("classroom_url", nargs="?",
                   help="https://www.skool.com/<community>/classroom/<course-id>")
    p.add_argument("--i-have-permission", action="store_true", dest="permission",
                   help="Required: confirm you are authorized to extract this content.")
    p.add_argument("--output-dir", default="./output")
    p.add_argument("--session-dir", default="./.skool_session")
    p.add_argument("--transcription-backend", default="faster-whisper",
                   choices=["faster-whisper", "openai", "none"])
    p.add_argument("--whisper-model", default="base")
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--no-transcripts", action="store_true")
    p.add_argument("--timestamps", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--only", metavar="LESSON_ID")
    p.add_argument("--module", metavar="NAME")
    p.add_argument("--headful", action="store_true")
    p.add_argument("--keep-audio", action="store_true")
    p.add_argument("--check-env", action="store_true",
                   help="Validate environment + binaries and exit.")
    p.add_argument("--debug-structure", action="store_true",
                   help="Dump the page's __NEXT_DATA__ shape and exit (for diagnosing parsing).")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--version", action="version", version=f"skool-extractor {__version__}")
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    log = setup_logging(verbose=args.verbose)

    if args.check_env:
        from .envcheck import run_check
        return run_check(args)

    if not args.classroom_url:
        log.error("A classroom URL is required. See --help.")
        return 1
    if not args.permission:
        log.error(
            "Refusing to run without --i-have-permission. This tool is only for "
            "content you are authorized to access (your own courses or with the "
            "creator's explicit permission)."
        )
        return 1

    try:
        settings = build_settings(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    try:
        return _run(settings)
    except KeyboardInterrupt:
        log.warning("Interrupted. Progress has been saved; re-run to resume.")
        return 130


def _select_lessons(course: Course, settings: Settings) -> list[Lesson]:
    lessons = list(course.iter_lessons())
    if settings.only_lesson:
        lessons = [l for l in lessons if l.id == settings.only_lesson]
    if settings.only_module:
        needle = settings.only_module.lower()
        lessons = [l for l in lessons
                   if any(needle in m.lower() for m in l.module_path)]
    return lessons


def _run(settings: Settings) -> int:
    from playwright.sync_api import sync_playwright

    from .auth import login as login_mod
    from .auth import session as session_mod
    from .fetch.page_fetcher import PageFetcher
    from .output import manifest as manifest_mod
    from .output import markdown_writer
    from .output.state import StateStore, notes_hash
    from .parse import next_data as nd
    from .parse import notes as notes_mod
    from .parse.tree_builder import build_course
    from .transcript import pipeline as transcript_pipeline
    from .video import cookies as cookies_mod
    from .video.resolver import resolve_video

    log = get_logger()
    started = _now_iso()

    with sync_playwright() as pw:
        browser, context = session_mod.launch_context(pw, settings)
        try:
            login_mod.login(context, settings)

            fetcher = PageFetcher(context, settings)
            emit("fetch_classroom", url=settings.classroom_url)
            html = fetcher.fetch_classroom(settings.classroom_url)

            data = nd.extract_next_data(html)

            if settings.debug_structure:
                from . import debug
                course_dir = settings.output_dir / f"{settings.community}__{settings.course_id}"
                dump_path = course_dir / "_debug_next_data.json"
                debug.dump_raw(data, dump_path)
                report = debug.summarize(data)
                log.info("Wrote raw __NEXT_DATA__ to %s", dump_path)
                print(report)
                log.info("Debug structure complete. Paste the report above back to continue.")
                fetcher.close()
                return 0

            root = nd.find_course_root(data, settings.course_id)
            course = build_course(root, settings.community, settings.course_id,
                                  settings.classroom_url)
            log.info("Parsed course '%s' with %d lessons", course.title,
                     course.lesson_count())
            emit("course_parsed", title=course.title, lessons=course.lesson_count())

            # Cookies for yt-dlp (Skool-native / Mux signed streams).
            cookie_file = cookies_mod.write_cookie_file(
                session_mod.storage_state_path(settings),
                settings.session_dir / "cookies.txt",
            )

            state = StateStore(settings.output_dir, course)
            manifest_mod.write_manifest(settings.output_dir, course, settings, started)
            media_dir = markdown_writer.course_dir(settings.output_dir, course) / "_media"

            lessons = _select_lessons(course, settings)
            total = len(lessons)
            errors = 0

            for index, lesson in enumerate(lessons, start=1):
                emit("lesson_start", index=index, total=total,
                     id=lesson.id, title=lesson.title)

                if state.should_skip(lesson, settings.force):
                    lesson.status = STATUS_SKIPPED
                    emit("lesson_skip", id=lesson.id, title=lesson.title)
                    continue

                try:
                    _process_lesson(lesson, settings, fetcher, media_dir,
                                    cookie_file, nd, notes_mod, resolve_video,
                                    transcript_pipeline)
                    markdown_writer.write_lesson(settings.output_dir, course, lesson,
                                                 timestamps=settings.timestamps)
                    lesson.notes_hash = notes_hash(lesson.notes_markdown)
                    lesson.extracted_at = _now_iso()
                    if lesson.transcript and lesson.transcript.error:
                        lesson.status = STATUS_PARTIAL
                    else:
                        lesson.status = STATUS_DONE
                except Exception as exc:  # noqa: BLE001 - isolate per-lesson failures
                    errors += 1
                    lesson.status = STATUS_ERROR
                    log.exception("Lesson failed: %s", lesson.title)
                    emit("lesson_error", id=lesson.id, error=str(exc))

                state.mark(lesson)
                manifest_mod.write_manifest(settings.output_dir, course, settings, started)
                emit("lesson_done", index=index, total=total, id=lesson.id,
                     status=lesson.status,
                     transcript=lesson.transcript.source if lesson.transcript else None)

            fetcher.close()
            manifest_mod.write_manifest(settings.output_dir, course, settings, started)

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


def _process_lesson(lesson, settings, fetcher, media_dir, cookie_file,
                    nd, notes_mod, resolve_video, transcript_pipeline) -> None:
    notes_html, notes_md = notes_mod.extract_notes(lesson.raw)
    video = resolve_video(lesson.raw)

    # Hydrate from the lesson deep-link if the course payload lacked notes/video.
    if notes_md is None and video is None:
        html = fetcher.fetch_lesson(settings.classroom_url, lesson.id)
        data = nd.extract_next_data(html)
        for node in nd.walk(data, lambda n: isinstance(n, dict)
                            and str(n.get("id")) == lesson.id
                            and isinstance(n.get("metadata"), dict)):
            lesson.raw = node
            notes_html, notes_md = notes_mod.extract_notes(node)
            video = resolve_video(node)
            break

    lesson.notes_html = notes_html
    lesson.notes_markdown = notes_md
    lesson.video = video
    lesson.transcript = transcript_pipeline.get_transcript(
        video, settings, media_dir, cookie_file)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
