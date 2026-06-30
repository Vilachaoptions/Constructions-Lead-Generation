"""Download a lesson video's audio track with yt-dlp.

Produces an m4a file under the course's ``_media`` dir. Skool cookies are passed
through so Skool-native / Mux (HLS) signed streams can be fetched. Requires
ffmpeg on PATH for audio extraction.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
from pathlib import Path
from typing import Optional

from ..logging_setup import get_logger
from ..models import VideoRef


class AudioDownloadError(Exception):
    pass


def download_audio(video: VideoRef, media_dir: Path,
                   cookie_file: Optional[Path] = None) -> Path:
    """Download audio for ``video`` into ``media_dir`` and return the file path."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise AudioDownloadError("yt-dlp is not installed") from exc

    media_dir.mkdir(parents=True, exist_ok=True)
    # Use a short, filesystem-safe name. For Mux/HLS the yt-dlp "id" is the whole
    # signed URL (with a huge token), which overflows the 255-char filename limit.
    safe_id = video.provider_id or hashlib.sha1(video.url.encode()).hexdigest()[:16]
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", safe_id)[:80]
    outtmpl = str(media_dir / f"{safe_id}.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        # Skool-native (Mux) playback URLs carry a domain restriction; Mux checks
        # the Referer/Origin against the allowed domain (skool.com).
        "http_headers": {
            "Referer": "https://www.skool.com/",
            "Origin": "https://www.skool.com",
        },
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
            "preferredquality": "128",
        }],
    }
    if cookie_file:
        opts["cookiefile"] = str(cookie_file)

    log = get_logger()
    log.info("Downloading audio (%s): %s", video.provider, video.url)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video.url, download=True)
    except Exception as exc:
        raise AudioDownloadError(f"yt-dlp failed for {video.url}: {exc}") from exc

    matches = glob.glob(str(media_dir / f"{safe_id}.m4a")) or \
        glob.glob(str(media_dir / f"{safe_id}.*"))
    if not matches:
        # fall back to most recent file in the dir
        files = sorted(media_dir.glob("*"), key=os.path.getmtime, reverse=True)
        matches = [str(files[0])] if files else []
    if not matches:
        raise AudioDownloadError(f"Audio file not found after download for {video.url}")
    return Path(matches[0])
