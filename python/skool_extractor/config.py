"""Settings: merge CLI args + environment (.env) into a single object.

Precedence: CLI arg > environment variable > built-in default.
Secrets (email/password/API key) come ONLY from the environment so they never
appear in shell history or process listings.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional at runtime; env vars still work
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


class ConfigError(Exception):
    """Raised when configuration is invalid or required values are missing."""


VALID_BACKENDS = ("faster-whisper", "openai", "none")


@dataclass
class Settings:
    classroom_url: str
    community: str
    course_id: str

    output_dir: Path
    session_dir: Path

    transcription_backend: str = "faster-whisper"
    whisper_model: str = "base"

    use_captions: bool = True
    transcripts_enabled: bool = True
    timestamps: bool = False

    force: bool = False
    only_lesson: Optional[str] = None
    only_module: Optional[str] = None

    headful: bool = False
    keep_audio: bool = False

    # politeness
    min_delay: float = 1.0
    jitter: float = 1.0

    # secrets (from env only)
    skool_email: Optional[str] = field(default=None, repr=False)
    skool_password: Optional[str] = field(default=None, repr=False)
    openai_api_key: Optional[str] = field(default=None, repr=False)

    def summary(self) -> dict:
        """Redacted, JSON-safe view for the manifest. Never includes secrets."""
        return {
            "classroom_url": self.classroom_url,
            "transcription_backend": self.transcription_backend,
            "whisper_model": self.whisper_model,
            "use_captions": self.use_captions,
            "transcripts_enabled": self.transcripts_enabled,
            "timestamps": self.timestamps,
        }


# Matches skool.com/<community>/classroom/<course-id> (with optional www, trailing path/query)
_CLASSROOM_RE = re.compile(
    r"skool\.com/(?P<community>[^/]+)/classroom/(?P<course>[^/?#]+)",
    re.IGNORECASE,
)


def parse_classroom_url(url: str) -> tuple[str, str]:
    """Extract (community, course_id) from a Skool classroom URL.

    Raises ConfigError if the URL doesn't look like a classroom URL.
    """
    match = _CLASSROOM_RE.search(url or "")
    if not match:
        raise ConfigError(
            "Could not parse classroom URL. Expected something like:\n"
            "  https://www.skool.com/<community>/classroom/<course-id>"
        )
    return match.group("community"), match.group("course")


def build_settings(args, env: Optional[dict] = None) -> Settings:
    """Build a Settings object from parsed argparse args + the environment.

    ``args`` is the argparse Namespace from cli.py. ``env`` defaults to os.environ
    (after loading .env) and is injectable for testing.
    """
    load_dotenv()
    env = env if env is not None else os.environ

    backend = args.transcription_backend
    if backend not in VALID_BACKENDS:
        raise ConfigError(
            f"--transcription-backend must be one of {VALID_BACKENDS}, got {backend!r}"
        )

    community, course_id = parse_classroom_url(args.classroom_url)

    settings = Settings(
        classroom_url=args.classroom_url,
        community=community,
        course_id=course_id,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        session_dir=Path(args.session_dir).expanduser().resolve(),
        transcription_backend=backend,
        whisper_model=args.whisper_model,
        use_captions=not args.no_captions,
        transcripts_enabled=not args.no_transcripts,
        timestamps=args.timestamps,
        force=args.force,
        only_lesson=args.only,
        only_module=args.module,
        headful=args.headful,
        keep_audio=args.keep_audio,
        skool_email=env.get("SKOOL_EMAIL"),
        skool_password=env.get("SKOOL_PASSWORD"),
        openai_api_key=env.get("OPENAI_API_KEY"),
    )

    if settings.transcription_backend == "openai" and not settings.openai_api_key:
        raise ConfigError(
            "--transcription-backend openai requires OPENAI_API_KEY in your environment / .env"
        )

    return settings
