"""Logging + machine-readable progress events.

Human logs go to stderr (so they never corrupt the progress stream). Progress
events are emitted as newline-delimited JSON on stdout, which the Node wrapper
parses to render a friendly progress display. Any non-JSON stdout line is
passed through by the wrapper unchanged.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_LOGGER_NAME = "skool_extractor"


def setup_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                                            datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def emit(event: str, **fields: Any) -> None:
    """Emit one newline-delimited JSON progress event on stdout."""
    payload = {"event": event, **fields}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
