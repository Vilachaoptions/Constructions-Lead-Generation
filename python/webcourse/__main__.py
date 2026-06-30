"""Entry point: ``python -m webcourse <command>``."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webcourse",
        description="Discover and extract non-Skool course platforms.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser(
        "discover",
        help="Open a browser, log in by hand, and dump a course page's structure.",
    )
    d.add_argument("url", help="A course or lesson URL on the site.")
    d.add_argument("--session-dir", default="./.webcourse_session")
    d.add_argument("--output-dir", default="./output")

    k = sub.add_parser(
        "kajabi",
        help="Extract a Kajabi course (notes + Wistia transcripts) using the saved session.",
    )
    k.add_argument("url", help="The Kajabi product/course URL.")
    k.add_argument("--session-dir", default="./.webcourse_session")
    k.add_argument("--output-dir", default="./output")
    k.add_argument("--transcription-backend", default="faster-whisper",
                   choices=["faster-whisper", "openai", "none"])
    k.add_argument("--whisper-model", default="base")
    k.add_argument("--no-captions", action="store_true")
    k.add_argument("--no-transcripts", action="store_true")
    k.add_argument("--timestamps", action="store_true")
    k.add_argument("--force", action="store_true")
    k.add_argument("--download-resources", action="store_true",
                   help="Also download attached files (PDFs, sheets, guides) per lesson.")
    k.add_argument("--only", metavar="POST_ID")
    k.add_argument("--verbose", "-v", action="store_true")

    pr = sub.add_parser(
        "probe", help="Dump a lesson page's download-button candidates (diagnostic).")
    pr.add_argument("url", help="A lesson URL that has a download button.")
    pr.add_argument("--session-dir", default="./.webcourse_session")
    pr.add_argument("--output-dir", default="./output")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        from .discover import run_discover
        return run_discover(args)
    if args.command == "kajabi":
        from .kajabi import run_kajabi
        return run_kajabi(args)
    if args.command == "probe":
        from .kajabi import run_probe
        return run_probe(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
