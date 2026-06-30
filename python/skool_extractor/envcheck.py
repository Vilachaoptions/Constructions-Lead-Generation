"""``--check-env``: validate the runtime before a real run.

Checks Python deps, the ffmpeg binary, the Playwright Chromium browser, and the
presence of credentials. Prints a checklist to stderr and returns a non-zero exit
code if anything required is missing.
"""

from __future__ import annotations

import importlib
import os
import shutil

from .logging_setup import get_logger

_REQUIRED_MODULES = [
    ("playwright", "playwright"),
    ("bs4", "beautifulsoup4"),
    ("markdownify", "markdownify"),
    ("yt_dlp", "yt-dlp"),
    ("youtube_transcript_api", "youtube-transcript-api"),
    ("webvtt", "webvtt-py"),
    ("faster_whisper", "faster-whisper"),
    ("tenacity", "tenacity"),
]


def run_check(args) -> int:
    log = get_logger()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ok = True

    def check(label: str, passed: bool, hint: str = "", required: bool = True) -> None:
        nonlocal ok
        mark = "OK  " if passed else ("FAIL" if required else "WARN")
        line = f"[{mark}] {label}"
        if not passed and hint:
            line += f"  -> {hint}"
        (log.info if passed else (log.error if required else log.warning))(line)
        if not passed and required:
            ok = False

    for module, pip_name in _REQUIRED_MODULES:
        try:
            importlib.import_module(module)
            check(f"python package: {pip_name}", True)
        except ImportError:
            check(f"python package: {pip_name}", False,
                  f"pip install {pip_name}")

    # ffmpeg
    check("ffmpeg on PATH", shutil.which("ffmpeg") is not None,
          "install ffmpeg (brew install ffmpeg / apt-get install ffmpeg)")

    # Playwright Chromium
    chromium_ok = True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
            chromium_ok = bool(path) and os.path.exists(path)
    except Exception:
        chromium_ok = False
    check("Playwright Chromium installed", chromium_ok,
          "run: playwright install chromium")

    # Credentials (warn only — a saved session may suffice)
    check("SKOOL_EMAIL / SKOOL_PASSWORD set", bool(os.environ.get("SKOOL_EMAIL"))
          and bool(os.environ.get("SKOOL_PASSWORD")),
          "set them in .env (not needed if a session is already saved)",
          required=False)

    if args.transcription_backend == "openai":
        check("OPENAI_API_KEY set", bool(os.environ.get("OPENAI_API_KEY")),
              "required for --transcription-backend openai")

    log.info("Environment check %s", "passed." if ok else "FAILED.")
    return 0 if ok else 1
