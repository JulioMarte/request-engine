import json
import logging

from request_engine.entrypoints.http.admin_console.observability import (
    ConsoleMetrics,
    ErrorEvent,
    ErrorTracker,
    JsonFormatter,
    redact,
)


def test_redact_masks_sensitive_keys_recursively() -> None:
    payload = {
        "login_handle": "owner",
        "password": "hunter2",
        "nested": {"access_token": "abc", "credential": {"rawId": "x"}},
        "items": [{"secret": "s", "name": "keep"}],
    }
    redacted = redact(payload)
    assert redacted["login_handle"] == "owner"
    assert redacted["password"] == "***"
    assert redacted["nested"]["access_token"] == "***"
    assert redacted["nested"]["credential"] == "***"
    assert redacted["items"][0]["secret"] == "***"
    assert redacted["items"][0]["name"] == "keep"


def test_json_formatter_emits_redacted_json() -> None:
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    setattr(record, "extra_fields", {"password": "hunter2", "path": "/a"})  # noqa: B010
    rendered = json.loads(JsonFormatter().format(record))
    assert rendered["message"] == "hello"
    assert rendered["password"] == "***"
    assert rendered["path"] == "/a"


def test_error_tracker_is_bounded_and_reversed() -> None:
    tracker = ErrorTracker(capacity=2)
    for index in range(3):
        tracker.record(
            ErrorEvent(
                at=f"t{index}",
                request_id=f"r{index}",
                kind="k",
                message="m",
            )
        )
    recent = tracker.recent()
    assert [event.request_id for event in recent] == ["r2", "r1"]
    assert tracker.total() == 2


def test_console_metrics_counts() -> None:
    metrics = ConsoleMetrics()
    metrics.observe_request(error=False)
    metrics.observe_request(error=True)
    metrics.observe_control_call(error=True)
    snapshot = metrics.snapshot()
    assert snapshot["requests"] == 2
    assert snapshot["errors"] == 1
    assert snapshot["control_calls"] == 1
    assert snapshot["control_errors"] == 1
