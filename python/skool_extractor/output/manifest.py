"""Write the JSON manifest: the full course tree + per-lesson status.

Written incrementally during a run so progress is visible (and so an interrupted
run still leaves a readable index).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import __version__
from ..config import Settings
from ..models import Course
from .markdown_writer import course_dir

MANIFEST_NAME = "manifest.json"


def manifest_path(output_root: Path, course: Course) -> Path:
    return course_dir(output_root, course) / MANIFEST_NAME


def write_manifest(output_root: Path, course: Course, settings: Settings,
                   generated_at: str) -> Path:
    base = course_dir(output_root, course)
    base.mkdir(parents=True, exist_ok=True)
    path = base / MANIFEST_NAME

    payload = {
        "tool": "skool-extractor",
        "tool_version": __version__,
        "generated_at": generated_at,
        "settings": settings.summary(),
        "course": course.to_dict(),
        "stats": _stats(course),
    }

    fd, tmp = tempfile.mkstemp(dir=str(base), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def _stats(course: Course) -> dict:
    counts: dict[str, int] = {}
    total = 0
    for lesson in course.iter_lessons():
        total += 1
        counts[lesson.status] = counts.get(lesson.status, 0) + 1
    return {"total_lessons": total, "by_status": counts}
