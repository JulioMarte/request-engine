"""Single reusable control-plane operation executor.

Both the generic operations console and the task-oriented resource workspaces
execute through this function, so there is exactly one execution path: build the
form fields from canonical OpenAPI metadata, coerce the submission, render the
path, attach an idempotency key when the operation requires one, and forward the
call. It owns no business policy; the control plane remains the authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any

import httpx

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.forms import (
    FormSubmissionError,
    build_fields,
    parse_submission,
    render_path,
)

_STEP_UP_CODES = frozenset({"phishing_resistant_auth_required", "recent_authentication_required"})


@dataclass(frozen=True)
class ExecutionOutcome:
    """A normalized result the templates can render without control-plane types."""

    status: int
    ok: bool
    payload_json: str
    error_code: str
    needs_step_up: bool
    retry_after: int | None
    idempotency_key: str | None

    def to_view(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "payload_json": self.payload_json,
            "error_code": self.error_code,
            "needs_step_up": self.needs_step_up,
            "retry_after": self.retry_after,
            "idempotency_key": self.idempotency_key,
        }


def form_error(message: str) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=422,
        ok=False,
        payload_json=json.dumps({"error": {"code": "form_error", "message": message}}),
        error_code="form_error",
        needs_step_up=False,
        retry_after=None,
        idempotency_key=None,
    )


def local_error(status: int, code: str, message: str) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=status,
        ok=False,
        payload_json=json.dumps({"error": {"code": code, "message": message}}),
        error_code=code,
        needs_step_up=False,
        retry_after=None,
        idempotency_key=None,
    )


def _from_response(response: Any, idempotency_key: str | None) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=response.status_code,
        ok=response.ok,
        payload_json=json.dumps(response.payload, indent=2, sort_keys=True, default=str),
        error_code=response.error_code or "",
        needs_step_up=response.error_code in _STEP_UP_CODES,
        retry_after=response.retry_after_seconds,
        idempotency_key=idempotency_key,
    )


async def execute_operation(
    state: Any,
    operation: AdminOperation,
    *,
    bearer: str | None,
    form: Mapping[str, str],
) -> ExecutionOutcome:
    """Execute one catalog operation from raw form values."""

    fields = build_fields(operation)
    try:
        submission = parse_submission(fields, form)
    except FormSubmissionError as exc:
        return form_error(str(exc))
    path = render_path(operation.path_template, submission.path_params)
    idempotency_key = token_urlsafe(24) if operation.requires_idempotency_key else None
    extra_headers = {"idempotency-key": idempotency_key} if idempotency_key else None
    try:
        response = await state.control_request(
            operation.method,
            path,
            bearer=bearer if operation.auth_kind == "bearer" else None,
            json_body=submission.body,
            params=submission.query_params or None,
            extra_headers=extra_headers,
        )
    except httpx.HTTPError as exc:
        return local_error(502, "control_unreachable", str(exc))
    return _from_response(response, idempotency_key)


__all__ = [
    "ExecutionOutcome",
    "execute_operation",
    "form_error",
    "local_error",
]
