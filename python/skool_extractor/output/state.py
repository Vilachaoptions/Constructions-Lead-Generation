"""Resume / idempotency state.

Tracks per-lesson completion keyed by lesson id + a content hash of the notes,
so re-runs skip lessons that are already extracted and unchanged. State lives in
``<course-dir>/.state.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from ..models import STATUS_DONE, Course, Lesson
from .markdown_writer import course_dir, lesson_filename, _module_dir

STATE_NAME = ".state.json"


def notes_hash(notes_markdown: Optional[str]) -> str:
    return hashlib.sha256((notes_markdown or "").encode("utf-8")).hexdigest()[:16]


class StateStore:
    def __init__(self, output_root: Path, course: Course):
        self._base = course_dir(output_root, course)
        self._path = self._base / STATE_NAME
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def should_skip(self, lesson: Lesson, force: bool) -> bool:
        """True if the lesson is already extracted and its Markdown still exists."""
        if force:
            return False
        record = self._data.get(lesson.id)
        if not record or record.get("status") != STATUS_DONE:
            return False
        md_path = _module_dir(self._base, lesson) / lesson_filename(lesson)
        return md_path.exists()

    def mark(self, lesson: Lesson) -> None:
        self._data[lesson.id] = {
            "status": lesson.status,
            "notes_hash": lesson.notes_hash,
            "extracted_at": lesson.extracted_at,
            "transcript_source": lesson.transcript.source if lesson.transcript else None,
        }
        self._save()

    def _save(self) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._base), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
