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
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        from .discover import run_discover
        return run_discover(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
