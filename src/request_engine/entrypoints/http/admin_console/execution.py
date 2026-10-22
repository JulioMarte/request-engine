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
_INTENT_FIELD = "_intent_id"
_MAX_INTENT_LENGTH = 128
# Upstream APIs answer in English. The console shows Spanish copy chosen by
# error code; the original upstream message stays in the technical details.
_HUMAN_ERRORS = {
    "platform_configuration_changed": (
        "La configuración cambió mientras usted la editaba. Recargue la página y revise "
        "la versión más reciente antes de intentarlo de nuevo."
    ),
    "phishing_resistant_auth_required": (
        "Confirme su identidad con una llave de acceso (passkey) para continuar. "
        "Lo que escribió se conserva."
    ),
    "recent_authentication_required": (
        "Confirme su sesión con su contraseña o una llave de acceso para continuar. "
        "Lo que escribió se conserva."
    ),
    "reauthentication_required": (
        "Confirme su sesión con su contraseña o una llave de acceso para continuar."
    ),
    "authentication_required": "Su sesión terminó. Inicie sesión de nuevo para continuar.",
    "setup_authentication_required": (
        "La sesión de configuración inicial terminó. Inicie una nueva sesión de configuración."
    ),
    "credential_invalid": "El correo, el usuario o la contraseña no son correctos. Revíselos.",
    "recovery_completion_required": (
        "Complete la recuperación de su cuenta en Seguridad de la cuenta antes de continuar."
    ),
    "password_work_capacity_exceeded": (
        "El servidor está ocupado verificando contraseñas. Espere un momento e intente de nuevo."
    ),
    "forbidden": "Usted no tiene permiso para hacer esta acción.",
    "not_found": "Este elemento no está disponible o usted ya no tiene acceso a él.",
    "revision_conflict": (
        "Alguien cambió esta información mientras usted la editaba. Recargue la página, "
        "revise los datos actuales e intente de nuevo."
    ),
    "validation_failed": "Algunos datos no son válidos. Revise el formulario e intente de nuevo.",
    "validation_error": "Algunos datos no son válidos. Revise el formulario e intente de nuevo.",
    "idempotency_conflict": (
        "Esta acción ya se envió con otros datos. Recargue la página e inicie la acción de nuevo."
    ),
    "reservation_already_served": (
        "Esta cita ya fue atendida. No se puede volver a registrar su llegada, "
        "cancelar ni cambiar de fecha."
    ),
    "rate_limited": "Se hicieron demasiados intentos. Espere un momento e intente de nuevo.",
    "control_unreachable": (
        "No se pudo conectar con el servidor. No se hizo ningún cambio. "
        "Revise su conexión e intente de nuevo."
    ),
    "tenant_context_missing": (
        "No se sabe a qué negocio pertenece esta acción. Abra el negocio desde Mis negocios "
        "e intente de nuevo."
    ),
    "outcome_unknown": (
        "La conexión se perdió antes de confirmar el resultado. Es posible que la acción "
        "se haya completado. Repita la misma acción sin cambios para confirmar el resultado "
        "de forma segura."
    ),
}
# Families of upstream codes, matched by suffix, for codes without their own copy.
_HUMAN_ERROR_SUFFIXES = (
    ("_not_found", "No se encontró lo que busca, o usted ya no tiene acceso. Recargue la página."),
    (
        "_revision_conflict",
        "Alguien cambió esta información mientras usted la editaba. Recargue la página, "
        "revise los datos actuales e intente de nuevo.",
    ),
    (
        "_conflict",
        "La acción choca con el estado actual. Recargue la página, revise los datos "
        "actuales e intente de nuevo.",
    ),
    ("_forbidden", "Usted no tiene permiso para hacer esta acción."),
    ("_invalid", "Algunos datos no son válidos. Revise el formulario e intente de nuevo."),
)
_GENERIC_FAILURE = (
    "No se pudo completar la acción. Revise los datos e intente de nuevo; "
    "los detalles técnicos muestran la respuesta del servidor."
)
_SUCCESS_MESSAGE = "La acción se completó correctamente."


def human_error(code: str, status: int | None = None) -> str:
    """Return Spanish copy for an upstream error code, never the raw English message."""

    if code in _HUMAN_ERRORS:
        return _HUMAN_ERRORS[code]
    for suffix, message in _HUMAN_ERROR_SUFFIXES:
        if code.endswith(suffix):
            return message
    if status == 401:
        return _HUMAN_ERRORS["authentication_required"]
    if status == 403:
        return _HUMAN_ERRORS["forbidden"]
    if status == 404:
        return _HUMAN_ERRORS["not_found"]
    if status == 429:
        return _HUMAN_ERRORS["rate_limited"]
    return _GENERIC_FAILURE


@dataclass(frozen=True)
class ExecutionOutcome:
    """A normalized result the templates can render without control-plane types."""

    status: int
    ok: bool
    payload_json: str
    message: str
    error_code: str
    needs_step_up: bool
    retry_after: int | None
    idempotency_key: str | None

    def to_view(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "payload_json": self.payload_json,
            "message": self.message,
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
        message=message,
        error_code="form_error",
        needs_step_up=False,
        retry_after=None,
        idempotency_key=None,
    )


def local_error(
    status: int,
    code: str,
    message: str,
    *,
    idempotency_key: str | None = None,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        status=status,
        ok=False,
        payload_json=json.dumps({"error": {"code": code, "message": message}}),
        message=_HUMAN_ERRORS.get(code, message),
        error_code=code,
        needs_step_up=False,
        retry_after=None,
        idempotency_key=idempotency_key,
    )


def _from_response(response: Any, idempotency_key: str | None) -> ExecutionOutcome:
    # The raw upstream message is English; it stays only in payload_json
    # (rendered under "Detalles técnicos"), never as the human message.
    message = (
        _SUCCESS_MESSAGE
        if response.ok
        else human_error(response.error_code or "", response.status_code)
    )
    return ExecutionOutcome(
        status=response.status_code,
        ok=response.ok,
        payload_json=json.dumps(response.payload, indent=2, sort_keys=True, default=str),
        message=message,
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
    surface: str = "control",
    organization_id: str | None = None,
) -> ExecutionOutcome:
    """Execute one catalog operation from raw form values."""

    fields = build_fields(operation)
    try:
        submission = parse_submission(fields, form)
        path = render_path(operation.path_template, submission.path_params)
    except FormSubmissionError as exc:
        return form_error(str(exc))
    intent_id = form.get(_INTENT_FIELD, "").strip()
    if len(intent_id) > _MAX_INTENT_LENGTH or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in intent_id
    ):
        return form_error("El formulario no es válido. Recargue la página e intente de nuevo.")
    idempotency_key = intent_id or token_urlsafe(24) if operation.requires_idempotency_key else None
    extra_headers = {"idempotency-key": idempotency_key} if idempotency_key else None
    try:
        request_method = state.control_request
        request_kwargs: dict[str, Any] = {}
        if surface == "runtime":
            if organization_id is None:
                return local_error(500, "tenant_context_missing", "organization context missing")
            request_method = state.runtime_request
            request_kwargs["organization_id"] = organization_id
        response = await request_method(
            operation.method,
            path,
            bearer=bearer if operation.auth_kind == "bearer" else None,
            json_body=submission.body,
            params=submission.query_params or None,
            extra_headers=extra_headers,
            **request_kwargs,
        )
    except httpx.TimeoutException:
        # A timeout is ambiguous: the upstream may have committed before the
        # response was lost. Preserve the stable intent key so an unchanged
        # replay can recover the canonical idempotent result.
        return local_error(
            504,
            "outcome_unknown",
            "The upstream response was not confirmed.",
            idempotency_key=idempotency_key,
        )
    except httpx.ConnectError:
        # Connect failures occur before an HTTP exchange is established. Keep
        # the intent key for a later retry, but do not claim the command ran.
        return local_error(
            502,
            "control_unreachable",
            "The upstream connection could not be established.",
            idempotency_key=idempotency_key,
        )
    except httpx.HTTPError:
        # Once a connection existed, transport failures such as a reset while
        # reading the response cannot prove rollback. Treat them like timeouts.
        return local_error(
            502,
            "outcome_unknown",
            "The upstream response was not confirmed.",
            idempotency_key=idempotency_key,
        )
    return _from_response(response, idempotency_key)


__all__ = [
    "ExecutionOutcome",
    "execute_operation",
    "form_error",
    "local_error",
]
