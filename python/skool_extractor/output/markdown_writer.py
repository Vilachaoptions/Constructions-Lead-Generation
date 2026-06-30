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
