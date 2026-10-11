"""Development-only mock of the Request Engine control plane.

This is NOT a control plane and NOT evidence of anything. It exists so the admin
console UI can be exercised in a browser without PostgreSQL, OpenBao or Docker.
It accepts any password/passkey credential, stores nothing durably, and must never
be deployed or used as proof. The real control plane remains the authority.

Run: python scripts/dev/mock_control_plane.py
"""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Request Engine mock control plane (dev only)")

_state: dict[str, Any] = {
    "claimed": False,
    "pending": None,
    "owner": None,
    "setup_sessions": {},
    "tokens": set(),
    "credentials": {},
}

_PLATFORM_OPS: list[tuple[str, str, str, str]] = [
    ("get", "/v1/platform/readiness", "platform_readiness_get", "platform.readiness.read"),
    ("get", "/v1/platform/observability", "platform_observability_get", "platform.readiness.read"),
    (
        "get",
        "/v1/platform/configurations",
        "platform_configuration_list",
        "platform.configuration.read",
    ),
    (
        "post",
        "/v1/platform/secrets",
        "platform_secret_create",
        "platform.secret.write",
    ),
    (
        "post",
        "/v1/platform/secrets/{binding_id}:rotate",
        "platform_secret_rotate",
        "platform.secret.rotate",
    ),
    (
        "put",
        "/v1/platform/deployment-recovery",
        "platform_deployment_recovery_configure",
        "platform.configuration.activate",
    ),
    (
        "get",
        "/v1/platform/deployment-recovery:plan",
        "platform_deployment_recovery_plan",
        "platform.configuration.read",
    ),
]


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _challenge() -> str:
    return _b64(secrets.token_bytes(32))


def _openapi() -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/v1/setup": {"get": {"operationId": "instanceSetupDiscovery", "tags": ["Instance setup"]}},
        "/v1/setup/sessions": {
            "post": {"operationId": "instanceSetupSessionCreate", "tags": ["Instance setup"]}
        },
        "/v1/setup/native-identity": {
            "post": {"operationId": "instanceSetupNativeIdentitySet", "tags": ["Instance setup"]}
        },
        "/v1/setup:finalize": {
            "post": {"operationId": "instanceSetupFinalize", "tags": ["Instance setup"]}
        },
    }
    for method, path, operation_id, capability in _PLATFORM_OPS:
        paths.setdefault(path, {})[method] = {
            "operationId": operation_id,
            "summary": operation_id.replace("_", " "),
            "tags": ["Platform administration"],
            "x-request-engine-capability": capability,
            "x-request-engine-owner": "platform",
            "x-request-engine-kind": "query" if method == "get" else "command",
            "x-request-engine-idempotency": "none" if method == "get" else "required",
            "x-request-engine-expected-revision": "none",
            "x-request-engine-exposure": "operator",
        }
    return {"openapi": "3.1.0", "info": {"title": "mock", "version": "0"}, "paths": paths}


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _setup_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "setup" and value.strip() else None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/openapi.json")
async def openapi() -> dict[str, Any]:
    return _openapi()


@app.get("/v1/setup")
async def setup_discovery() -> dict[str, bool]:
    return {"setup_required": not _state["claimed"]}


@app.post("/v1/setup/sessions", status_code=201)
async def setup_session() -> JSONResponse:
    if _state["claimed"]:
        return _error(409, "instance_setup_closed", "setup is closed")
    token = secrets.token_urlsafe(24)
    _state["setup_sessions"][token] = {"created_at": datetime.now(UTC).isoformat()}
    return JSONResponse(
        {
            "setup_session_id": "00000000-0000-0000-0000-000000000001",
            "token": token,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        },
        status_code=201,
    )


@app.post("/v1/setup/native-identity", status_code=204)
async def setup_identity(request: Request) -> Response:
    token = _setup_bearer(request)
    if token is None or token not in _state["setup_sessions"]:
        return _error(401, "setup_authentication_required", "invalid setup bearer")
    body = await request.json()
    _state["pending"] = {
        "login_handle": body.get("login_handle"),
        "password": body.get("password"),
    }
    return Response(status_code=204)


@app.post("/v1/setup/webauthn/registration-options")
async def setup_webauthn_options(request: Request) -> JSONResponse:
    token = _setup_bearer(request)
    if token is None or token not in _state["setup_sessions"]:
        return _error(401, "setup_authentication_required", "invalid setup bearer")
    handle = (_state["pending"] or {}).get("login_handle") or "owner"
    return JSONResponse(
        {
            "public_key": {
                "challenge": _challenge(),
                "rp": {"id": "localhost", "name": "Request Engine"},
                "user": {
                    "id": _b64(secrets.token_bytes(16)),
                    "name": handle,
                    "displayName": handle,
                },
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60000,
                "attestation": "none",
                "authenticatorSelection": {
                    "userVerification": "required",
                    "residentKey": "preferred",
                },
                "excludeCredentials": [],
            }
        }
    )


@app.post("/v1/setup/webauthn/registrations", status_code=204)
async def setup_webauthn_register(request: Request) -> Response:
    token = _setup_bearer(request)
    if token is None or token not in _state["setup_sessions"]:
        return _error(401, "setup_authentication_required", "invalid setup bearer")
    body = await request.json()
    credential = body.get("credential") or {}
    handle = (_state["pending"] or {}).get("login_handle") or "owner"
    _state["credentials"][handle] = credential.get("id") or "unknown"
    return Response(status_code=204)


@app.post("/v1/setup/recovery-codes", status_code=201)
async def setup_recovery_codes(request: Request) -> JSONResponse:
    token = _setup_bearer(request)
    if token is None or token not in _state["setup_sessions"]:
        return _error(401, "setup_authentication_required", "invalid setup bearer")
    codes = [f"MOCK-{secrets.token_hex(3).upper()}-{index}" for index in range(10)]
    return JSONResponse({"codes": codes}, status_code=201)


@app.post("/v1/setup:finalize", status_code=201)
async def setup_finalize(request: Request) -> JSONResponse:
    token = _setup_bearer(request)
    if token is None or token not in _state["setup_sessions"]:
        return _error(401, "setup_authentication_required", "invalid setup bearer")
    body = await request.json()
    pending = _state["pending"]
    if not pending:
        return _error(409, "instance_setup_step_invalid", "identity not set")
    _state["owner"] = pending
    _state["claimed"] = True
    _state["setup_sessions"].pop(token, None)
    return JSONResponse(
        {
            "instance_id": "00000000-0000-0000-0000-0000000000aa",
            "owner_principal_id": "00000000-0000-0000-0000-0000000000bb",
            "native_identity_id": "00000000-0000-0000-0000-0000000000cc",
            "policy_key": "platform-owner-v1",
            "claim_provenance": body.get("claim_provenance"),
        },
        status_code=201,
    )


@app.post("/auth/native/sessions")
async def native_login(request: Request) -> JSONResponse:
    body = await request.json()
    owner = _state["owner"]
    if not _state["claimed"] or not owner:
        return _error(409, "instance_setup_required", "instance not claimed")
    if body.get("login_handle") != owner.get("login_handle") or body.get("password") != owner.get(
        "password"
    ):
        return _error(401, "invalid_credentials", "invalid login or password")
    token = secrets.token_urlsafe(24)
    _state["tokens"].add(token)
    return JSONResponse({"access_token": token, "token_type": "Bearer"})


@app.delete("/auth/native/sessions/current", status_code=204)
async def native_logout(request: Request) -> Response:
    token = _bearer(request)
    if token:
        _state["tokens"].discard(token)
    return Response(status_code=204)


@app.post("/auth/native/webauthn/authentication-options")
async def webauthn_options(request: Request) -> JSONResponse:
    body = await request.json()
    handle = str(body.get("login_handle") or "owner")
    credential_id = _state["credentials"].get(handle)
    allow = [{"type": "public-key", "id": credential_id}] if credential_id else []
    return JSONResponse(
        {
            "public_key": {
                "challenge": _challenge(),
                "rpId": "localhost",
                "timeout": 60000,
                "userVerification": "required",
                "allowCredentials": allow,
            }
        }
    )


@app.post("/auth/native/webauthn/sessions")
async def webauthn_login(request: Request) -> JSONResponse:
    body = await request.json()
    if not body.get("credential"):
        return _error(401, "credential_invalid", "missing credential")
    token = secrets.token_urlsafe(24)
    _state["tokens"].add(token)
    return JSONResponse({"access_token": token, "token_type": "Bearer"})


@app.post("/auth/native/sessions/current/webauthn/step-up-options")
async def step_up_options() -> JSONResponse:
    return JSONResponse(
        {
            "public_key": {
                "challenge": _challenge(),
                "rpId": "localhost",
                "timeout": 60000,
                "userVerification": "required",
                "allowCredentials": [],
            }
        }
    )


@app.post("/auth/native/sessions/current/webauthn/step-up")
async def step_up() -> dict[str, Any]:
    return {"authenticated_at": datetime.now(UTC).isoformat(), "user_verified": True}


@app.get("/v1/platform/readiness")
async def readiness(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"status": "ready", "setup_required": not _state["claimed"]})


@app.get("/v1/platform/observability")
async def observability(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"backup_evidence": "unknown", "restore_drill": "unknown"})


@app.get("/v1/platform/configurations")
async def configurations(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"revisions": []})


@app.post("/v1/platform/secrets", status_code=201)
async def create_secret(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"binding_id": "mock-binding", "version": 1}, status_code=201)


@app.post("/v1/platform/secrets/{binding_id}:rotate")
async def rotate_secret(binding_id: str, request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"binding_id": binding_id, "version": 2, "step_up_required": True})


@app.put("/v1/platform/deployment-recovery")
async def configure_deployment(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"status": "activated"})


@app.get("/v1/platform/deployment-recovery:plan")
async def deployment_plan(request: Request) -> JSONResponse:
    if _bearer(request) not in _state["tokens"]:
        return _error(401, "authentication_required", "bearer required")
    return JSONResponse({"status": "in_sync", "changed_fields": []})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
