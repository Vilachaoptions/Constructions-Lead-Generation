# Skool Classroom Extractor

Extract a [Skool.com](https://www.skool.com) classroom's full content — the module/lesson
tree, each lesson's **notes** (the rich-text lesson body), and a **transcript** of each
lesson's video — into clean, reusable files: one Markdown file per lesson plus a JSON
manifest of the whole course.

> ⚠️ **Use responsibly.** This tool is intended **only** for content you are authorized to
> access — your own courses, or courses where you have the creator's explicit permission.
> Automated extraction of other people's course content may violate Skool's Terms of Service
> and copyright law. You must pass `--i-have-permission` to run. Defaults are deliberately
> polite (serial, throttled). The tool never bypasses captchas.

## How it works

Skool is a Next.js app: a classroom's entire structure — modules, lessons, lesson notes, and
video links — is embedded in the page's `__NEXT_DATA__` JSON. The extractor logs in with
Playwright, parses that JSON into a course tree, and for each lesson:

1. Converts the lesson notes (HTML / rich-text) to Markdown.
2. Builds a transcript — **existing captions first** (YouTube, Vimeo, Loom, Wistia), and for
   uncaptioned videos (typically Skool-native / Mux uploads) it downloads the audio and
   transcribes it with **Whisper** (`faster-whisper` locally, or the OpenAI Whisper API).

The result is written as `output/<community>__<course>/NN-module/NN-lesson.md` plus a
`manifest.json`. Re-runs are **resumable** — already-extracted lessons are skipped.

## Architecture

A **Python core** (`python/skool_extractor/`) does all the real work. A **thin Node.js CLI
wrapper** (`bin/skool-extract.js`) spawns the Python core and streams its output — there is no
scraping logic in Node, so Python stays the single source of truth.

## Setup

```bash
# 1. Python core
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 2. System dependency: ffmpeg (required for audio extraction + Whisper)
#    macOS:  brew install ffmpeg
#    Ubuntu: sudo apt-get install ffmpeg

# 3. Node wrapper (optional — you can also call the Python core directly)
npm install

# 4. Credentials
cp .env.example .env                 # then edit SKOOL_EMAIL / SKOOL_PASSWORD
```

Verify everything is in place:

```bash
npm run check-env          # or: python -m skool_extractor --check-env
```

## Usage

```bash
# Node wrapper
npx skool-extract "https://www.skool.com/<community>/classroom/<course-id>" --i-have-permission

# …or the Python core directly (identical args)
python -m skool_extractor "https://www.skool.com/<community>/classroom/<course-id>" --i-have-permission
```

First run with 2FA? Do a **one-time interactive login** so the session is saved for later
headless runs:

```bash
python -m skool_extractor "<classroom-url>" --i-have-permission --headful
```

### Common options

| Option | Default | Purpose |
|---|---|---|
| `<classroom-url>` (positional) | — | `skool.com/<community>/classroom/<course-id>` |
| `--i-have-permission` | — | **required** acknowledgement that you're authorized |
| `--output-dir DIR` | `./output` | where Markdown + manifest are written |
| `--session-dir DIR` | `./.skool_session` | where the login session is cached |
| `--transcription-backend` | `faster-whisper` | `faster-whisper` \| `openai` \| `none` |
| `--whisper-model NAME` | `base` | local model size (`tiny`/`base`/`small`/`medium`/…) |
| `--no-captions` | off | skip caption tracks, always use Whisper |
| `--no-transcripts` | off | notes only, no transcripts |
| `--timestamps` | off | include `[mm:ss]` timestamps in the transcript |
| `--only LESSON_ID` | — | extract a single lesson |
| `--module NAME` | — | extract only modules whose title contains NAME |
| `--force` | off | re-extract even already-done lessons |
| `--headful` | off | show the browser (first login / 2FA) |
| `--keep-audio` | off | keep downloaded audio files |
| `--check-env` | off | validate Python/ffmpeg/Chromium/env and exit |

Secrets (`SKOOL_EMAIL`, `SKOOL_PASSWORD`, `OPENAI_API_KEY`) come **only** from `.env`, never
from CLI args, so they don't leak into shell history.

## Output layout

```
output/<community>__<course>/
├── manifest.json                 # machine-readable course tree + per-lesson status
├── 01-getting-started/
│   ├── 01-welcome.md             # front-matter + ## Notes + ## Transcript
│   └── 02-setup.md
└── 02-advanced/
    └── 01-deep-dive.md
```

## Development

```bash
pip install -r requirements.txt
pytest                 # Python unit tests over saved __NEXT_DATA__ fixtures
npm test               # Node wrapper spawn-contract test
```
