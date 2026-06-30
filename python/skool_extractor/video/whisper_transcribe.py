"""Transcribe an audio file with Whisper.

Two backends:
  * ``faster-whisper`` (default): local CTranslate2 inference, CPU int8 fallback.
  * ``openai``: the OpenAI Whisper API (chunking left simple — large files should
    prefer the local backend).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..logging_setup import get_logger
from ..models import SOURCE_WHISPER, Transcript, TranscriptSegment


class TranscriptionError(Exception):
    pass


def transcribe(audio_path: Path, backend: str, model: str,
               openai_api_key: Optional[str] = None) -> Transcript:
    if backend == "faster-whisper":
        return _faster_whisper(audio_path, model)
    if backend == "openai":
        return _openai_whisper(audio_path, openai_api_key)
    raise TranscriptionError(f"Unknown transcription backend: {backend}")


def _faster_whisper(audio_path: Path, model: str) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise TranscriptionError("faster-whisper is not installed") from exc

    log = get_logger()
    log.info("Transcribing with faster-whisper (model=%s): %s", model, audio_path.name)
    # int8 on CPU keeps memory/latency reasonable; works without a GPU.
    whisper = WhisperModel(model, device="auto", compute_type="int8")
    segments_iter, info = whisper.transcribe(str(audio_path))

    segments = [
        TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
        for seg in segments_iter if seg.text.strip()
    ]
    return Transcript(
        source=SOURCE_WHISPER,
        text=" ".join(s.text for s in segments).strip(),
        language=getattr(info, "language", None),
        segments=segments,
        model=f"faster-whisper:{model}",
    )


def _openai_whisper(audio_path: Path, api_key: Optional[str]) -> Transcript:
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY is required for the openai backend")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise TranscriptionError("openai package is not installed") from exc

    log = get_logger()
    log.info("Transcribing with OpenAI Whisper API: %s", audio_path.name)
    client = OpenAI(api_key=api_key)
    with audio_path.open("rb") as fh:
        resp = client.audio.transcriptions.create(
            model="whisper-1", file=fh, response_format="verbose_json",
        )

    segments: list[TranscriptSegment] = []
    for seg in (getattr(resp, "segments", None) or []):
        text = (seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", "")).strip()
        if not text:
            continue
        start = seg.get("start") if isinstance(seg, dict) else getattr(seg, "start", None)
        end = seg.get("end") if isinstance(seg, dict) else getattr(seg, "end", None)
        segments.append(TranscriptSegment(start=start, end=end, text=text))

    text = getattr(resp, "text", "") or " ".join(s.text for s in segments)
    return Transcript(
        source=SOURCE_WHISPER,
        text=text.strip(),
        language=getattr(resp, "language", None),
        segments=segments,
        model="openai:whisper-1",
    )
