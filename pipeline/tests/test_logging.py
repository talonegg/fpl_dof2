from __future__ import annotations

import io
import json
import logging

from fpl_dof.obs.logging import configure_logging, get_logger, run_context, stage_context


def test_records_are_json_and_carry_run_and_stage() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    log = get_logger("test.logging")

    with run_context("run-123"), stage_context("ingest"):
        log.info("fetched", extra={"endpoint": "bootstrap-static", "count": 3})

    payload = json.loads(stream.getvalue().strip())
    assert payload["run_id"] == "run-123"
    assert payload["stage"] == "ingest"
    assert payload["message"] == "fetched"
    assert payload["endpoint"] == "bootstrap-static"
    assert payload["count"] == 3
    assert payload["level"] == "INFO"
    assert payload["ts"].endswith("+00:00")


def test_context_is_restored_after_exit() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    log = get_logger("test.logging")
    with run_context("run-a"):
        pass
    log.info("outside")
    assert json.loads(stream.getvalue().strip())["run_id"] == "-"


def test_exception_is_serialised() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    log = get_logger("test.logging")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
    payload = json.loads(stream.getvalue().strip())
    assert "ValueError: boom" in payload["exception"]
    logging.getLogger().handlers.clear()
