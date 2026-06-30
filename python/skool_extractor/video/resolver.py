"""Resolve a lesson's raw video field(s) into a typed ``VideoRef``.

Skool lessons reference videos hosted on mixed providers. We detect the provider
by URL/host pattern and keep the canonical URL for downstream caption/audio work.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..models import VideoRef

# metadata keys observed to hold a lesson's video link
_VIDEO_KEYS = ("videoLink", "videoLinks", "video", "videoUrl", "video_url", "media")

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

_PROVIDER_PATTERNS = (
    ("youtube", re.compile(r"(youtube\.com|youtu\.be)", re.I)),
    ("vimeo", re.compile(r"vimeo\.com", re.I)),
    ("loom", re.compile(r"loom\.com", re.I)),
    ("wistia", re.compile(r"(wistia\.com|wistia\.net|wi\.st)", re.I)),
    ("mux", re.compile(r"(stream\.mux\.com|mux\.com|\.m3u8)", re.I)),
)


def detect_provider(url: str) -> str:
    for name, pattern in _PROVIDER_PATTERNS:
        if pattern.search(url):
            return name
    return "unknown"


def _first_url(value) -> Optional[str]:
    """Pull the first http(s) URL out of a string / list / JSON-encoded list."""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith(("[", "{")):
            try:
                return _first_url(json.loads(s))
            except (json.JSONDecodeError, ValueError):
                pass
        m = _URL_RE.search(s)
        return m.group(0) if m else None
    if isinstance(value, list):
        for item in value:
            found = _first_url(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key in ("url", "link", "href", "src"):
            if value.get(key):
                found = _first_url(value[key])
                if found:
                    return found
        # otherwise scan all values
        for v in value.values():
            found = _first_url(v)
            if found:
                return found
    return None


_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})")
_VIMEO_ID_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def _provider_id(provider: str, url: str) -> Optional[str]:
    if provider == "youtube":
        m = _YT_ID_RE.search(url)
        return m.group(1) if m else None
    if provider == "vimeo":
        m = _VIMEO_ID_RE.search(url)
        return m.group(1) if m else None
    return None


def resolve_video(lesson_raw: Optional[dict]) -> Optional[VideoRef]:
    """Return a VideoRef for the lesson, or None if it has no video."""
    if not isinstance(lesson_raw, dict):
        return None
    metadata = lesson_raw.get("metadata")
    if not isinstance(metadata, dict):
        return None

    raw_value = None
    for key in _VIDEO_KEYS:
        if metadata.get(key):
            raw_value = metadata[key]
            break
    if raw_value is None:
        return None

    url = _first_url(raw_value)
    if not url:
        return None

    provider = detect_provider(url)
    return VideoRef(
        provider=provider,
        url=url,
        provider_id=_provider_id(provider, url),
        raw=raw_value if isinstance(raw_value, str) else json.dumps(raw_value)[:500],
    )
