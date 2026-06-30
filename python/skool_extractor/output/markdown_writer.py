"""Write one Markdown file per lesson: front-matter + Notes + Transcript.

Files are named ``NN-slug.md`` (zero-padded by order) and laid out under a
directory tree that mirrors the course's modules. Writes are atomic
(temp file + rename) so an interrupted run never leaves a half-written file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..models import SOURCE_NONE, Course, Lesson
from ..parse.tree_builder import slugify


def course_dir(output_root: Path, course: Course) -> Path:
    return output_root / f"{course.community}__{course.slug}"


def _module_dir(base: Path, lesson: Lesson) -> Path:
    """Build the nested module directory path for a lesson."""
    path = base
    for depth, title in enumerate(lesson.module_path):
        path = path / f"{depth + 1:02d}-{slugify(title)}"
    return path


def lesson_filename(lesson: Lesson) -> str:
    return f"{lesson.order + 1:02d}-{slugify(lesson.title)}.md"


def _format_timestamp(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_markdown(lesson: Lesson, timestamps: bool = False) -> str:
    video = lesson.video
    transcript = lesson.transcript

    fm = ["---",
          f'id: "{lesson.id}"',
          f'title: "{lesson.title.replace(chr(34), chr(39))}"',
          f'module_path: {lesson.module_path}',
          f'video_url: "{video.url if video else ""}"',
          f'video_provider: "{video.provider if video else ""}"',
          f'transcript_source: "{transcript.source if transcript else SOURCE_NONE}"',
          f'extracted_at: "{lesson.extracted_at or ""}"',
          "---", ""]

    body = [f"# {lesson.title}", ""]

    body.append("## Notes")
    body.append("")
    body.append(lesson.notes_markdown.strip() if lesson.notes_markdown else "_No notes._")
    body.append("")

    body.append("## Transcript")
    body.append("")
    if transcript and transcript.text:
        if timestamps and transcript.segments:
            for seg in transcript.segments:
                ts = _format_timestamp(seg.start) if seg.start is not None else "--:--"
                body.append(f"**[{ts}]** {seg.text}")
            body.append("")
        else:
            body.append(transcript.text.strip())
            body.append("")
        body.append(f"_Source: {transcript.source}"
                    + (f" ({transcript.model})" if transcript.model else "") + "_")
    elif transcript and transcript.error:
        body.append(f"_Transcript unavailable: {transcript.error}_")
    else:
        body.append("_No transcript available._")
    body.append("")

    return "\n".join(fm + body)


def write_lesson(output_root: Path, course: Course, lesson: Lesson,
                 timestamps: bool = False) -> Path:
    """Render and atomically write a lesson's Markdown file. Returns the path."""
    base = course_dir(output_root, course)
    target_dir = _module_dir(base, lesson)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / lesson_filename(lesson)

    content = render_markdown(lesson, timestamps=timestamps)
    fd, tmp = tempfile.mkstemp(dir=str(target_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    lesson.markdown_path = str(path.relative_to(base))
    return path


def _strip_front_matter(text: str) -> str:
    """Remove a leading YAML front-matter block (--- ... ---) from a lesson file."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            return text[nl + 1:].lstrip("\n") if nl != -1 else ""
    return text


def write_master(output_root: Path, course: Course) -> Path:
    """Write a single master document combining every lesson, in course order.

    Built from the per-lesson Markdown files already on disk, so it works even
    on resumed runs where lessons were skipped. Includes a table of contents and
    each lesson's notes + transcript, grouped by section.
    """
    base = course_dir(output_root, course)
    base.mkdir(parents=True, exist_ok=True)
    lessons = list(course.iter_lessons())

    lines: list[str] = [
        f"# {course.title} — Full Course",
        "",
        f"_{len(lessons)} lessons · community: {course.community}_",
        "",
        "## Contents",
        "",
    ]
    for i, lesson in enumerate(lessons, start=1):
        crumb = " / ".join(lesson.module_path)
        prefix = f"{crumb} / " if crumb else ""
        lines.append(f"{i}. {prefix}{lesson.title}")
    lines.append("")

    for i, lesson in enumerate(lessons, start=1):
        path = _module_dir(base, lesson) / lesson_filename(lesson)
        crumb = " / ".join(lesson.module_path) or "(top level)"
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"> **Lesson {i}/{len(lessons)}** · {crumb}")
        lines.append("")
        if path.exists():
            lines.append(_strip_front_matter(path.read_text(encoding="utf-8")).rstrip())
        else:
            lines.append(f"# {lesson.title}\n\n_Not extracted._")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    dest = base / f"00-{slugify(course.title)}-MASTER.md"
    fd, tmp = tempfile.mkstemp(dir=str(base), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest
