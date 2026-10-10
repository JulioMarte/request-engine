"""Black-box managed SMTP scenarios for the reusable system E2E runner.

All Request Engine interaction is over the control-plane HTTP API. Provider
state and accepted-message receipts come from the simulator's separate HTTP
control/receipt API; this module does not import application internals or use
database/Docker authority.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import cast


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    bearer: str | None = None,
    idempotency_key: str | None = None,
    smtp_control_token: str | None = None,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if smtp_control_token:
        headers["X-SMTP-Lab-Control"] = smtp_control_token
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, content = exc.code, exc.read()
    if status not in expected:
        raise RuntimeError(f"SMTP lab HTTP operation failed with status {status}")
    try:
        decoded: object = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SMTP lab HTTP operation returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("SMTP lab HTTP operation returned a non-object response")
    return status, cast(dict[str, object], decoded)


def run_provider_outcome_matrix(
    *,
    control_url: str,
    provider_url: str = "http://smtp-provider:8091",
    provider_control_token: str,
    bearer: str,
    revision: int,
    idempotency_prefix: str,
) -> dict[str, object]:
    """Exercise real STARTTLS SMTP outcomes through managed-provider HTTP.

    The caller supplies a valid, already validated `email.delivery` revision
    that points to the SMTP lab service. Every case performs one provider-test
    command. The external receipt API is the oracle for accepted versus
    rejected DATA, including accept-then-drop ambiguity.
    """
    _, secret = _request_json(
        "POST",
        f"{control_url}/v1/platform/secrets",
        bearer=bearer,
        idempotency_key=f"{idempotency_prefix}-invalid-secret-create",
        payload={
            "purpose": "email.smtp.password",
            "value": "smtp-lab-invalid-credential",
        },
        expected=(201,),
    )
    binding_id = secret.get("binding_id")
    if not isinstance(binding_id, str):
        raise RuntimeError("SMTP negative credential fixture omitted its secret binding")
    _, staged = _request_json(
        "POST",
        f"{control_url}/v1/platform/configurations/email.delivery/revisions",
        bearer=bearer,
        idempotency_key=f"{idempotency_prefix}-invalid-config-stage",
        payload={
            "provider_kind": "smtp",
            "configuration": {
                "host": "smtp-provider",
                "port": 1025,
                "sender": "smtp-lab@example.test",
                "security": "starttls",
                "username": "smtp-lab-user",
            },
            "secret_binding_id": binding_id,
        },
        expected=(201,),
    )
    invalid_revision = staged.get("revision")
    if not isinstance(invalid_revision, int):
        raise RuntimeError("SMTP negative credential revision was not returned")
    _request_json(
        "POST",
        f"{provider_url}/control/reset",
        payload={},
        smtp_control_token=provider_control_token,
    )
    _request_json(
        "POST",
        (
            f"{control_url}/v1/platform/configurations/email.delivery/revisions/"
            f"{invalid_revision}:validate"
        ),
        bearer=bearer,
        idempotency_key=f"{idempotency_prefix}-invalid-config-validate",
        expected=(422,),
    )
    _, invalid_attempts = _request_json("GET", f"{provider_url}/attempts")
    auth_value = invalid_attempts.get("auth_attempts")
    invalid_data_value = invalid_attempts.get("data_attempts")
    if not isinstance(auth_value, list) or not isinstance(invalid_data_value, list):
        raise RuntimeError("invalid SMTP credential attempt evidence has an invalid shape")
    auth_attempts = cast(list[object], auth_value)
    if len(auth_attempts) != 1 or not isinstance(auth_attempts[0], dict):
        raise RuntimeError("invalid SMTP credential attempt evidence has an invalid shape")
    auth_attempt = cast(dict[str, object], auth_attempts[0])
    if auth_attempt.get("accepted") is not False or invalid_data_value:
        raise RuntimeError("invalid SMTP credentials were not rejected before DATA")
    _, invalid_receipts = _request_json("GET", f"{provider_url}/messages")
    if invalid_receipts.get("messages") != []:
        raise RuntimeError("invalid SMTP credentials produced an accepted message")

    cases: list[dict[str, object]] = []
    for index, (behavior, expected_outcome, expected_detail) in enumerate(
        (
            ("accept", "delivered", "smtp_test_delivered"),
            ("reject_transient", "failed", "smtp_test_temporarily_rejected"),
            ("reject_permanent", "failed", "smtp_test_rejected"),
            ("accept_then_drop", "unknown", "smtp_test_delivery_unknown"),
        ),
        start=1,
    ):
        _request_json(
            "POST",
            f"{provider_url}/control/reset",
            payload={},
            smtp_control_token=provider_control_token,
        )
        if behavior != "accept":
            _request_json(
                "POST",
                f"{provider_url}/control/behavior",
                payload={"behavior": behavior},
                smtp_control_token=provider_control_token,
            )
        _, result = _request_json(
            "POST",
            f"{control_url}/v1/platform/providers/email.delivery/{revision}:test",
            bearer=bearer,
            idempotency_key=f"{idempotency_prefix}-{index}",
            payload={"destination": f"smtp-case-{index}@example.test"},
        )
        _, attempts_payload = _request_json("GET", f"{provider_url}/attempts")
        attempts_value = attempts_payload.get("data_attempts")
        if not isinstance(attempts_value, list):
            raise RuntimeError("SMTP provider-test omitted its DATA attempt list")
        attempt_values = cast(list[object], attempts_value)
        if len(attempt_values) != 1:
            raise RuntimeError("one SMTP provider-test did not produce exactly one DATA attempt")
        if not isinstance(attempt_values[0], dict):
            raise RuntimeError("SMTP DATA attempt evidence is not an object")
        attempt = cast(dict[str, object], attempt_values[0])
        if attempt.get("behavior") != behavior:
            raise RuntimeError("SMTP lab recorded a different response mode")
        _, messages_payload = _request_json("GET", f"{provider_url}/messages")
        messages_value = messages_payload.get("messages")
        if not isinstance(messages_value, list):
            raise RuntimeError("SMTP receipt API omitted its messages list")
        messages = cast(list[object], messages_value)
        accepted = behavior in {"accept", "accept_then_drop"}
        if bool(attempt.get("accepted")) is not accepted or len(messages) != int(accepted):
            raise RuntimeError("independent SMTP receipt API disagrees with DATA outcome")
        receipt: dict[str, object] | None = None
        if accepted:
            if not isinstance(messages[0], dict):
                raise RuntimeError("SMTP receipt metadata is not an object")
            receipt = cast(dict[str, object], messages[0])
            if receipt.get("message_id") != attempt.get("message_id"):
                raise RuntimeError("SMTP receipt did not match the DATA attempt Message-ID")

        # Compare the managed operation's result to the independent receipt
        # API. In particular, UNKNOWN must have exactly one observed attempt.
        if (
            result.get("outcome") != expected_outcome
            or result.get("detail_code") != expected_detail
        ):
            raise RuntimeError("managed SMTP provider result has an incorrect classification")
        cases.append(
            {
                "behavior": behavior,
                "outcome": expected_outcome,
                "accepted_by_provider": accepted,
                "data_attempts": len(attempt_values),
                "receipt_matches_message_id": not accepted
                or (receipt is not None and receipt.get("message_id") == attempt.get("message_id")),
            }
        )
    # Leave the simulator in a fresh accepting state for the governed worker
    # delivery journey that follows this provider-outcome matrix.
    _request_json(
        "POST",
        f"{provider_url}/control/reset",
        payload={},
        smtp_control_token=provider_control_token,
    )
    return {
        "invalid_credentials": {
            "validation_rejected": True,
            "data_attempts": 0,
            "accepted_messages": 0,
        },
        "cases": cases,
    }


def wait_for_accepted_sender(
    *,
    provider_url: str = "http://smtp-provider:8091",
    sender: str,
    timeout_seconds: float = 60,
) -> list[str]:
    """Return accepted Message-IDs observed through the provider's HTTP API."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _, payload = _request_json("GET", f"{provider_url}/messages")
        values = payload.get("messages")
        if not isinstance(values, list):
            raise RuntimeError("SMTP receipt API omitted its messages list")
        matches: list[dict[str, object]] = []
        for item in cast(list[object], values):
            if not isinstance(item, dict):
                continue
            message = cast(dict[str, object], item)
            if (
                message.get("sender") == sender
                and message.get("subject") == "Request Engine identity recovery"
            ):
                matches.append(message)
        if matches:
            return [
                str(item["message_id"])
                for item in matches
                if isinstance(item.get("message_id"), str) and item["message_id"]
            ]
        time.sleep(0.5)
    raise RuntimeError("SMTP provider receipt API did not observe the expected recovery sender")


def set_provider_behavior(
    behavior: str,
    *,
    provider_url: str = "http://smtp-provider:8091",
    control_token: str,
) -> None:
    _request_json(
        "POST",
        f"{provider_url}/control/reset",
        payload={},
        smtp_control_token=control_token,
    )
    if behavior != "accept":
        _request_json(
            "POST",
            f"{provider_url}/control/behavior",
            payload={"behavior": behavior},
            smtp_control_token=control_token,
        )


def verify_ambiguous_worker_delivery(
    *,
    control_url: str,
    bearer: str,
    case_id: str,
    issue_idempotency_key: str,
    provider_url: str = "http://smtp-provider:8091",
    timeout_seconds: float = 60,
) -> dict[str, object]:
    """Prove accept-then-drop is UNKNOWN and replay does not send again."""
    deadline = time.monotonic() + timeout_seconds
    delivery_status: object = None
    while time.monotonic() < deadline:
        _, current = _request_json(
            "GET",
            f"{control_url}/v1/platform/identity-recovery-cases/{case_id}",
            bearer=bearer,
        )
        delivery_status = current.get("delivery_status")
        if delivery_status in ("unknown", "failed", "delivered"):
            break
        time.sleep(0.5)
    if delivery_status != "unknown":
        raise RuntimeError("ambiguous SMTP recovery did not settle to UNKNOWN")

    _, attempts_before = _request_json("GET", f"{provider_url}/attempts")
    attempt_list = attempts_before.get("data_attempts")
    _, receipts_before = _request_json("GET", f"{provider_url}/messages")
    receipt_list = receipts_before.get("messages")
    if not isinstance(attempt_list, list) or not isinstance(receipt_list, list):
        raise RuntimeError("ambiguous SMTP attempt/receipt evidence has an invalid shape")
    attempt_values = cast(list[object], attempt_list)
    receipt_values = cast(list[object], receipt_list)
    if len(attempt_values) != 1 or len(receipt_values) != 1:
        raise RuntimeError("ambiguous SMTP delivery lacks exactly one provider attempt/receipt")
    if not isinstance(attempt_values[0], dict) or not isinstance(receipt_values[0], dict):
        raise RuntimeError("ambiguous SMTP attempt/receipt evidence is not an object")
    attempt = cast(dict[str, object], attempt_values[0])
    receipt = cast(dict[str, object], receipt_values[0])
    if (
        attempt.get("accepted") is not True
        or attempt.get("behavior") != "accept_then_drop"
        or receipt.get("message_id") != attempt.get("message_id")
    ):
        raise RuntimeError("independent SMTP receipt does not match the unknown attempt")

    # The same semantic issue request is an idempotent replay, not permission
    # to resend the ambiguous SMTP transmission.
    _request_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:issue",
        bearer=bearer,
        idempotency_key=issue_idempotency_key,
        payload={"expected_revision": 2},
        expected=(202,),
    )
    _, attempts_after = _request_json("GET", f"{provider_url}/attempts")
    after_values = attempts_after.get("data_attempts")
    if not isinstance(after_values, list) or cast(list[object], after_values) != attempt_values:
        raise RuntimeError("idempotent replay caused another SMTP DATA attempt")
    _, current = _request_json(
        "GET",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}",
        bearer=bearer,
    )
    if current.get("delivery_status") != "unknown":
        raise RuntimeError("idempotent issue replay changed the UNKNOWN delivery result")
    return {
        "delivery_status": "unknown",
        "provider_accepted_data": True,
        "receipt_matches_message_id": True,
        "attempts_before_replay": 1,
        "attempts_after_replay": 1,
    }
