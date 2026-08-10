"""Structured JSON logging with the run_id threaded through every record.

One line of JSON per event on stderr. Human-readable output is not a goal: these logs are read by
grep and by the run manifest, and a run that failed at 03:30 AEST is diagnosed from them.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")
STAGE: contextvars.ContextVar[str] = contextvars.ContextVar("stage", default="-")

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a record as a single JSON object, including any extra fields it carries."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "run_id": RUN_ID.get(),
            "stage": STAGE.get(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", *, stream: Any | None = None) -> None:
    """Install the JSON formatter on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # httpx logs every request at INFO. A ~570-request sweep then buries our own events under
    # its own transcript; the run manifest already records the call counts that matter.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def run_context(run_id: str) -> Iterator[None]:
    token = RUN_ID.set(run_id)
    try:
        yield
    finally:
        RUN_ID.reset(token)


@contextmanager
def stage_context(stage: str) -> Iterator[None]:
    token = STAGE.set(stage)
    try:
        yield
    finally:
        STAGE.reset(token)
