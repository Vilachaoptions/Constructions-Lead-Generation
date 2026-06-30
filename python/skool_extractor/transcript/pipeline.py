"""Per-lesson transcript strategy: captions first, then Whisper fallback.

Owns the temp-audio lifecycle and converts every failure into a
``Transcript(source="none", error=...)`` so a single bad video never aborts a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import Settings
from ..logging_setup import get_logger
from ..models import SOURCE_NONE, Transcript, VideoRef
from ..video import audio as audio_mod
from ..video import captions as captions_mod
from ..video import whisper_transcribe


def get_transcript(video: Optional[VideoRef], settings: Settings,
                   media_dir: Path, cookie_file: Optional[Path]) -> Transcript:
    log = get_logger()

    if not settings.transcripts_enabled:
        return Transcript(source=SOURCE_NONE)
    if video is None:
        return Transcript(source=SOURCE_NONE)

    # 1. Captions first (unless disabled).
    if settings.use_captions:
        try:
            caption_t = captions_mod.get_captions(video, cookie_file)
            if caption_t and caption_t.text:
                return caption_t
        except Exception as exc:  # noqa: BLE001 - never abort a run on captions
            log.debug("Caption extraction errored for %s: %s", video.url, exc)

    # 2. Whisper fallback.
    if settings.transcription_backend == "none":
        return Transcript(source=SOURCE_NONE, error="no captions; whisper disabled")

    audio_path: Optional[Path] = None
    try:
        audio_path = audio_mod.download_audio(video, media_dir, cookie_file)
        transcript = whisper_transcribe.transcribe(
            audio_path,
            backend=settings.transcription_backend,
            model=settings.whisper_model,
            openai_api_key=settings.openai_api_key,
        )
        return transcript
    except Exception as exc:  # noqa: BLE001
        log.warning("Transcription failed for %s: %s", video.url, exc)
        return Transcript(source=SOURCE_NONE, error=str(exc))
    finally:
        if audio_path and audio_path.exists() and not settings.keep_audio:
            try:
                audio_path.unlink()
            except OSError:  # pragma: no cover
                pass
