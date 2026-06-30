"""Extract existing caption / subtitle tracks for a lesson's video.

Strategy by provider:
  * YouTube  -> youtube-transcript-api (fast, no download); fall back to yt-dlp.
  * others   -> yt-dlp, which can list & fetch subtitle/VTT tracks when present.

Returns a ``Transcript(source="captions")`` or ``None`` when no track exists.
"""

from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path
from typing import Optional

from ..logging_setup import get_logger
from ..models import SOURCE_CAPTIONS, Transcript, TranscriptSegment, VideoRef


def get_captions(video: VideoRef, cookie_file: Optional[Path] = None) -> Optional[Transcript]:
    if video.provider == "youtube":
        t = _youtube_captions(video)
        if t:
            return t
    return _ytdlp_captions(video, cookie_file)


def _youtube_captions(video: VideoRef) -> Optional[Transcript]:
    if not video.provider_id:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:  # pragma: no cover
        return None
    try:
        entries = YouTubeTranscriptApi.get_transcript(video.provider_id)
    except Exception as exc:  # no transcript / disabled / network
        get_logger().debug("YouTube transcript unavailable: %s", exc)
        return None

    segments = [
        TranscriptSegment(start=e.get("start"),
                          end=(e.get("start", 0) + e.get("duration", 0)
                               if e.get("start") is not None else None),
                          text=e.get("text", "").strip())
        for e in entries if e.get("text", "").strip()
    ]
    if not segments:
        return None
    return Transcript(source=SOURCE_CAPTIONS, model="youtube",
                      text=_join(segments), segments=segments)


def _ytdlp_captions(video: VideoRef, cookie_file: Optional[Path]) -> Optional[Transcript]:
    try:
        import yt_dlp
    except ImportError:  # pragma: no cover
        return None

    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en.*"],
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        if "mux.com" in video.url:
            opts["http_headers"] = {"Referer": "https://www.skool.com/",
                                    "Origin": "https://www.skool.com"}
        if cookie_file:
            opts["cookiefile"] = str(cookie_file)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([video.url])
        except Exception as exc:
            get_logger().debug("yt-dlp caption fetch failed: %s", exc)
            return None

        vtts = glob.glob(os.path.join(tmp, "*.vtt"))
        if not vtts:
            return None
        segments = parse_vtt(vtts[0])
        if not segments:
            return None
        return Transcript(source=SOURCE_CAPTIONS, model=f"{video.provider}-captions",
                          text=_join(segments), segments=segments)


def parse_vtt(path: str) -> list[TranscriptSegment]:
    """Parse a VTT file into segments, de-duplicating rolling auto-caption lines."""
    try:
        import webvtt
    except ImportError:  # pragma: no cover
        return []
    try:
        captions = webvtt.read(path)
    except Exception:
        return []

    segments: list[TranscriptSegment] = []
    last_text = None
    for cap in captions:
        text = " ".join(line.strip() for line in cap.text.splitlines() if line.strip())
        if not text or text == last_text:
            continue
        last_text = text
        segments.append(TranscriptSegment(start=_ts(cap.start),
                                          end=_ts(cap.end), text=text))
    return segments


def _ts(value: str) -> Optional[float]:
    """Convert a VTT timestamp 'HH:MM:SS.mmm' to seconds."""
    try:
        parts = value.split(":")
        parts = [float(p) for p in parts]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        h, m, s = parts[-3], parts[-2], parts[-1]
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


def _join(segments: list[TranscriptSegment]) -> str:
    return " ".join(s.text for s in segments).strip()
