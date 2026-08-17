"""Tests for structured logging.

These tests own their capture buffer rather than using ``capsys``. A ``StreamHandler`` binds
its stream when it is constructed, and pytest swaps ``sys.stderr`` between the setup and call
phases, so a handler built in a fixture would write into a buffer the test body cannot read.
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable, Iterator

import pytest

from aedifex.config import Environment, LogFormat, Settings
from aedifex.infrastructure.observability import logging as logging_module
from aedifex.infrastructure.observability.logging import (
    PIPELINE_CONTEXT_KEYS,
    bind_job_context,
    configure_logging,
    get_logger,
    log_stage,
    new_request_id,
)

ConfigureLogs = Callable[..., io.StringIO]


@pytest.fixture(autouse=True)
def _reset_logging_state() -> Iterator[None]:
    """Logging configuration is process-global; reset it so tests cannot leak into each other."""
    yield
    logging_module._configured = False


@pytest.fixture
def capture_logs(monkeypatch: pytest.MonkeyPatch) -> ConfigureLogs:
    """Return a function that configures logging into a fresh, readable buffer."""

    def _configure(log_level: str = "DEBUG", log_format: LogFormat = LogFormat.JSON) -> io.StringIO:
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buffer)
        configure_logging(
            Settings(environment=Environment.TEST, log_format=log_format, log_level=log_level),
            force=True,
        )
        return buffer

    return _configure


@pytest.fixture
def json_logs(capture_logs: ConfigureLogs) -> io.StringIO:
    return capture_logs()


def emitted_lines(captured: str) -> list[dict[str, object]]:
    """Parse the JSON log lines out of a capture buffer."""
    return [json.loads(line) for line in captured.strip().splitlines() if line.startswith("{")]


class TestConfiguration:
    def test_is_idempotent(self) -> None:
        configure_logging(Settings(environment=Environment.TEST))
        assert logging_module._configured is True
        # A second call must not reconfigure; importing a module that logs is harmless.
        configure_logging(Settings(environment=Environment.TEST))
        assert logging_module._configured is True

    def test_repeated_configuration_does_not_duplicate_output(
        self, capture_logs: ConfigureLogs
    ) -> None:
        """Adding a handler per call would multiply every subsequent log line."""
        capture_logs()
        buffer = capture_logs()
        get_logger("test").info("once")
        assert len(emitted_lines(buffer.getvalue())) == 1

    def test_console_format_is_available_for_local_development(
        self, capture_logs: ConfigureLogs
    ) -> None:
        buffer = capture_logs(log_format=LogFormat.CONSOLE)
        get_logger("test").info("readable.event")
        output = buffer.getvalue()
        assert "readable.event" in output
        assert not output.startswith("{")

    def test_get_logger_configures_on_first_use(self) -> None:
        logging_module._configured = False
        get_logger("test")
        assert logging_module._configured is True

    def test_request_ids_are_unique(self) -> None:
        assert len({new_request_id() for _ in range(100)}) == 100


class TestJsonOutput:
    def test_emits_one_json_object_per_line(self, json_logs: io.StringIO) -> None:
        get_logger("test").info("thing.happened", document_id="abc")
        records = emitted_lines(json_logs.getvalue())
        assert len(records) == 1
        assert records[0]["event"] == "thing.happened"
        assert records[0]["document_id"] == "abc"

    def test_stamps_service_and_version(self, json_logs: io.StringIO) -> None:
        """Findings must be reproducible, which requires knowing the build that produced them."""
        get_logger("test").info("thing.happened")
        record = emitted_lines(json_logs.getvalue())[0]
        assert record["service"] == "aedifex"
        assert record["version"]

    def test_includes_level_logger_and_timestamp(self, json_logs: io.StringIO) -> None:
        get_logger("test").warning("careful")
        record = emitted_lines(json_logs.getvalue())[0]
        assert record["level"] == "warning"
        assert record["logger"] == "test"
        assert "timestamp" in record

    def test_level_filtering_is_applied(self, capture_logs: ConfigureLogs) -> None:
        buffer = capture_logs(log_level="WARNING")
        logger = get_logger("test")
        logger.debug("invisible")
        logger.info("also.invisible")
        logger.warning("visible")
        assert [record["event"] for record in emitted_lines(buffer.getvalue())] == ["visible"]

    def test_exception_info_is_rendered_as_a_string_field(self, json_logs: io.StringIO) -> None:
        def fail() -> None:
            raise ValueError("boom")

        try:
            fail()
        except ValueError:
            get_logger("test").error("failed", exc_info=True)
        record = emitted_lines(json_logs.getvalue())[0]
        assert "ValueError" in str(record["exception"])

    def test_stdlib_loggers_are_rendered_in_the_same_format(self, json_logs: io.StringIO) -> None:
        """Uvicorn and SQLAlchemy log through stdlib; a deployment must parse one format."""
        import logging

        logging.getLogger("some.library").warning("library message")
        record = emitted_lines(json_logs.getvalue())[0]
        assert record["event"] == "library message"
        assert record["logger"] == "some.library"
        assert record["service"] == "aedifex"


class TestContextBinding:
    def test_context_appears_on_log_lines(self, json_logs: io.StringIO) -> None:
        with bind_job_context(source_id="cpwd", job_id="job-1"):
            get_logger("test").info("stage.ran")
        record = emitted_lines(json_logs.getvalue())[0]
        assert record["source_id"] == "cpwd"
        assert record["job_id"] == "job-1"

    def test_context_is_removed_on_exit(self, json_logs: io.StringIO) -> None:
        """Leaked context would attribute one document's logs to another."""
        with bind_job_context(source_id="cpwd"):
            pass
        get_logger("test").info("later.event")
        assert "source_id" not in emitted_lines(json_logs.getvalue())[0]

    def test_context_is_restored_after_an_exception(self, json_logs: io.StringIO) -> None:
        with pytest.raises(RuntimeError), bind_job_context(source_id="cpwd"):
            raise RuntimeError("boom")
        get_logger("test").info("later.event")
        assert "source_id" not in emitted_lines(json_logs.getvalue())[0]

    def test_nested_contexts_merge_and_unwind(self, json_logs: io.StringIO) -> None:
        logger = get_logger("test")
        with bind_job_context(source_id="cpwd"):
            with bind_job_context(document_id="doc-1"):
                logger.info("inner")
            logger.info("outer")
        records = emitted_lines(json_logs.getvalue())
        assert records[0]["source_id"] == "cpwd"
        assert records[0]["document_id"] == "doc-1"
        assert records[1]["source_id"] == "cpwd"
        assert "document_id" not in records[1]

    def test_canonical_keys_are_declared(self) -> None:
        """Dashboards depend on these names, so the list is a contract."""
        for key in ("request_id", "job_id", "source_id", "document_id", "stage", "duration_ms"):
            assert key in PIPELINE_CONTEXT_KEYS


class TestLogStage:
    def test_success_emits_started_and_completed_with_duration(
        self, json_logs: io.StringIO
    ) -> None:
        with log_stage("download", source_id="cpwd"):
            pass
        records = emitted_lines(json_logs.getvalue())
        assert [record["event"] for record in records] == ["download.started", "download.completed"]
        assert records[1]["status"] == "completed"
        assert isinstance(records[1]["duration_ms"], float)
        assert all(record["source_id"] == "cpwd" for record in records)

    def test_failure_is_logged_with_error_detail(self, json_logs: io.StringIO) -> None:
        with pytest.raises(ValueError), log_stage("download", document_id="doc-1"):
            raise ValueError("network exploded")
        records = emitted_lines(json_logs.getvalue())
        assert records[1]["event"] == "download.failed"
        assert records[1]["status"] == "failed"
        assert records[1]["error_type"] == "ValueError"
        assert records[1]["error"] == "network exploded"
        assert records[1]["document_id"] == "doc-1"
        assert "duration_ms" in records[1]

    def test_the_exception_is_re_raised(self, json_logs: io.StringIO) -> None:
        """Logging a failure must never convert it into a silent success."""
        with pytest.raises(ValueError, match="boom"), log_stage("download"):
            raise ValueError("boom")

    def test_stage_name_is_on_every_line(self, json_logs: io.StringIO) -> None:
        with log_stage("classify"):
            pass
        records = emitted_lines(json_logs.getvalue())
        assert records
        assert all(record["stage"] == "classify" for record in records)
