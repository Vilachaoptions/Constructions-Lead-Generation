"""Core data models for the course tree, videos, and transcripts.

Plain stdlib dataclasses keep the model dependency-free and trivially
serializable for the JSON manifest (see ``output/manifest.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# --- Lesson status values (used in manifest + resume state) ---------------
STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_PARTIAL = "partial"   # notes written but transcript failed
STATUS_SKIPPED = "skipped"   # already extracted, skipped on this run
STATUS_ERROR = "error"

# --- Transcript sources ---------------------------------------------------
SOURCE_CAPTIONS = "captions"
SOURCE_WHISPER = "whisper"
SOURCE_NONE = "none"


@dataclass
class VideoRef:
    """A resolved reference to a lesson's video on some provider."""

    provider: str               # youtube | vimeo | loom | wistia | mux | skool | unknown
    url: str
    provider_id: Optional[str] = None
    raw: Optional[str] = None    # original field value, for debugging

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "url": self.url,
            "provider_id": self.provider_id,
        }


@dataclass
class TranscriptSegment:
    start: Optional[float]      # seconds
    end: Optional[float]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class Transcript:
    source: str                 # captions | whisper | none
    text: str = ""
    language: Optional[str] = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    model: Optional[str] = None   # whisper model name or caption provider
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "language": self.language,
            "model": self.model,
            "error": self.error,
            "segment_count": len(self.segments),
        }


@dataclass
class Lesson:
    id: str                       # the ?md=<lesson-id> value
    title: str
    order: int = 0
    module_path: list[str] = field(default_factory=list)
    url: str = ""                 # deep link with ?md=
    notes_html: Optional[str] = None
    notes_markdown: Optional[str] = None
    video: Optional[VideoRef] = None
    transcript: Optional[Transcript] = None
    status: str = STATUS_PENDING
    extracted_at: Optional[str] = None
    notes_hash: Optional[str] = None
    markdown_path: Optional[str] = None   # relative to output course dir
    raw: Optional[dict] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "order": self.order,
            "module_path": self.module_path,
            "url": self.url,
            "video": self.video.to_dict() if self.video else None,
            "transcript": self.transcript.to_dict() if self.transcript else None,
            "status": self.status,
            "extracted_at": self.extracted_at,
            "markdown_path": self.markdown_path,
        }


@dataclass
class Module:
    id: str
    title: str
    order: int = 0
    parent_id: Optional[str] = None
    lessons: list[Lesson] = field(default_factory=list)
    submodules: list["Module"] = field(default_factory=list)

    def iter_lessons(self):
        """Yield every lesson in this module and its submodules, in order."""
        for lesson in self.lessons:
            yield lesson
        for sub in self.submodules:
            yield from sub.iter_lessons()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "order": self.order,
            "parent_id": self.parent_id,
            "lessons": [l.to_dict() for l in self.lessons],
            "submodules": [m.to_dict() for m in self.submodules],
        }


@dataclass
class Course:
    id: str
    community: str
    title: str
    slug: str = ""
    url: str = ""
    modules: list[Module] = field(default_factory=list)
    raw: Optional[dict] = field(default=None, repr=False)

    def iter_lessons(self):
        """Yield every lesson across all modules, in document order."""
        for module in self.modules:
            yield from module.iter_lessons()

    def lesson_count(self) -> int:
        return sum(1 for _ in self.iter_lessons())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "community": self.community,
            "title": self.title,
            "slug": self.slug,
            "url": self.url,
            "modules": [m.to_dict() for m in self.modules],
        }
