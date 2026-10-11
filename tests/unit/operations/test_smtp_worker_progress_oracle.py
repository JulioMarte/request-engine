"""Falsifiers for the lab oracle; real worker evidence belongs to Docker E2E."""

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = [pytest.mark.unit, pytest.mark.contract]


@pytest.mark.parametrize("duplicate", [None, "attempt", "receipt"])
def test_ambiguity_oracle_rechecks_exact_message_after_worker_progress(
    monkeypatch: pytest.MonkeyPatch, duplicate: str | None
) -> None:
    helper = runpy.run_path(str(ROOT / "tests/system_e2e/smtp_provider_suite.py"))[
        "verify_ambiguous_worker_delivery"
    ]
    attempt: dict[str, object] = {
        "message_id": "ambiguous-id",
        "accepted": True,
        "behavior": "accept_then_drop",
    }
    receipt: dict[str, object] = {"message_id": "ambiguous-id", "to": ["ambiguous@example.test"]}
    progress_attempt: dict[str, object] = {
        "message_id": "progress-id",
        "accepted": True,
        "behavior": "accept",
    }
    progress_receipt: dict[str, object] = {
        "message_id": "progress-id",
        "to": ["progress@example.test"],
    }
    progressed = False
    replayed = False
    reads_after_progress: list[str] = []

    def request(method: str, url: str, **kwargs: object) -> tuple[int, dict[str, object]]:
        nonlocal replayed
        if url.endswith("ambiguous:issue"):
            assert method == "POST"
            replayed = True
            return 202, {}
        if url.endswith("/progress"):
            assert progressed
            return 200, {"delivery_status": "delivered"}
        if url.endswith("/ambiguous"):
            return 200, {"delivery_status": "unknown"}
        if url.endswith("/attempts"):
            values = [attempt]
            if progressed:
                reads_after_progress.append("attempts")
                values += [progress_attempt]
                if duplicate == "attempt":
                    values += [dict(attempt)]
            return 200, {"data_attempts": values}
        if url.endswith("/messages"):
            values = [receipt]
            if progressed:
                reads_after_progress.append("receipts")
                values += [progress_receipt]
                if duplicate == "receipt":
                    values += [dict(receipt)]
            return 200, {"messages": values}
        raise AssertionError(f"unexpected lab request: {url}")

    def progress() -> tuple[str, str]:
        nonlocal progressed
        assert replayed
        progressed = True
        return "progress", "progress@example.test"

    monkeypatch.setitem(helper.__globals__, "_request_json", request)
    arguments = dict(
        control_url="http://control",
        bearer="test-only",
        case_id="ambiguous",
        issue_idempotency_key="original-issue",
        issue_progress_delivery=progress,
        provider_url="http://provider",
    )
    if duplicate is not None:
        with pytest.raises(RuntimeError, match="another SMTP DATA|receipt changed"):
            helper(**arguments)
    else:
        evidence = helper(**arguments)
        assert evidence["subsequent_governed_delivery_completed"] is True
        assert evidence["attempts_after_replay"] == 1
        assert reads_after_progress == ["receipts", "attempts", "receipts"]


def test_progress_barrier_requires_both_delivered_case_and_provider_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = runpy.run_path(str(ROOT / "tests/system_e2e/smtp_provider_suite.py"))[
        "_wait_for_progress_delivery"
    ]
    ticks = iter([0, 0, 2])
    monkeypatch.setattr(helper.__globals__["time"], "monotonic", lambda: next(ticks))

    def no_sleep(_seconds: float) -> None:
        pass

    monkeypatch.setattr(helper.__globals__["time"], "sleep", no_sleep)

    def request(method: str, url: str, **kwargs: object) -> tuple[int, dict[str, object]]:
        if url.endswith("/messages"):
            return 200, {"messages": []}
        return 200, {"delivery_status": "delivered"}

    monkeypatch.setitem(helper.__globals__, "_request_json", request)
    with pytest.raises(RuntimeError, match="did not complete"):
        helper(
            control_url="http://control",
            bearer="test-only",
            case_id="progress",
            destination="progress@example.test",
            provider_url="http://provider",
            timeout_seconds=1,
        )


@pytest.mark.parametrize(
    ("auth_attempts", "expected_error"),
    [
        ([{"mechanism": "PLAIN", "accepted": False}], None),
        (
            [{"mechanism": "PLAIN", "accepted": False}, {"mechanism": "LOGIN", "accepted": False}],
            None,
        ),
        ([{"mechanism": "PLAIN", "accepted": True}], "not rejected before DATA"),
        ([], "invalid shape"),
    ],
)
def test_invalid_credential_oracle_allows_fallback_only_when_every_auth_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    auth_attempts: list[dict[str, object]],
    expected_error: str | None,
) -> None:
    helper = runpy.run_path(str(ROOT / "tests/system_e2e/smtp_provider_suite.py"))[
        "verify_invalid_credentials"
    ]
    revoked = False

    def request(method: str, url: str, **kwargs: object) -> tuple[int, dict[str, object]]:
        nonlocal revoked
        if url.endswith("/secrets"):
            return 201, {
                "binding_id": "invalid-credential-binding",
                "revision": 3,
                "backend_version": 4,
            }
        if url.endswith(":revoke"):
            assert kwargs["payload"] == {"expected_revision": 3, "expected_backend_version": 4}
            revoked = True
            return 200, {"binding_id": "invalid-credential-binding", "status": "revoked"}
        if url.endswith("/revisions"):
            return 201, {"revision": 1}
        if url.endswith(":validate"):
            return 422, {}
        if url.endswith("/attempts"):
            return 200, {"auth_attempts": auth_attempts, "data_attempts": []}
        if url.endswith("/messages"):
            return 200, {"messages": []}
        return 200, {}

    monkeypatch.setitem(helper.__globals__, "_request_json", request)
    arguments = dict(
        control_url="http://control",
        provider_url="http://provider",
        provider_control_token="test-only",
        bearer="test-only",
        idempotency_prefix="test-oracle",
    )
    if expected_error is not None:
        with pytest.raises(RuntimeError, match=expected_error):
            helper(**arguments)
        assert revoked is False
    else:
        evidence = helper(**arguments)
        assert evidence["validation_rejected"] is True
        assert evidence["invalid_binding_revoked"] is True
        assert revoked is True
