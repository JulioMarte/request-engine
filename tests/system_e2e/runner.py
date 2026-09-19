from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

from fido2.utils import websafe_decode
from software_webauthn_authenticator import SoftwareAuthenticator

FORBIDDEN_ENV_FRAGMENTS = (
    "DATABASE_URL",
    "MIGRATION",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
)


def _checkpoint(name: str, status: str, detail: str = "") -> dict[str, str]:
    item = {
        "name": name,
        "status": status,
        "detail": detail,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(item, sort_keys=True), flush=True)
    return item


def _write_checkpoints(artifact_dir: Path, checkpoints: list[dict[str, str]]) -> None:
    (artifact_dir / "checkpoints.json").write_text(
        json.dumps(checkpoints, indent=2) + "\n",
        encoding="utf-8",
    )


def _json_object(path: Path) -> dict[str, object]:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid E2E handoff file: {path.name}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"E2E handoff file is not an object: {path.name}")
    return cast(dict[str, object], decoded)


def _required_string(data: dict[str, object], key: str, source: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{source} is missing {key}")
    return value


def _http_request(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    bearer: str | None = None,
    setup_token: str | None = None,
    idempotency_key: str | None = None,
    organization_id: str | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if setup_token is not None:
        headers["Authorization"] = f"Setup {setup_token}"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if organization_id is not None:
        headers["X-RE-Organization-ID"] = organization_id
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if response.status not in expected_statuses:
                raise RuntimeError(
                    f"{method} {url} returned HTTP {response.status}: {response_body[:300]}"
                )
            return response.status, response_body
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        if exc.code in expected_statuses:
            return exc.code, response_body
        message = f"{method} {url} returned HTTP {exc.code}: {response_body[:300]}"
        raise RuntimeError(message) from exc


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    bearer: str | None = None,
    setup_token: str | None = None,
    idempotency_key: str | None = None,
    organization_id: str | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> dict[str, object]:
    _, body = _http_request(
        method,
        url,
        payload=payload,
        bearer=bearer,
        setup_token=setup_token,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        expected_statuses=expected_statuses,
    )
    try:
        decoded: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {url} did not return valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{method} {url} returned a non-object JSON document")
    return cast(dict[str, object], decoded)


def _http_json_array(
    method: str,
    url: str,
    *,
    bearer: str | None = None,
    organization_id: str | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> list[dict[str, object]]:
    _, body = _http_request(
        method,
        url,
        bearer=bearer,
        organization_id=organization_id,
        expected_statuses=expected_statuses,
    )
    try:
        decoded: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {url} did not return valid JSON") from exc
    if not isinstance(decoded, list):
        raise RuntimeError(f"{method} {url} returned a non-array JSON document")
    result: list[dict[str, object]] = []
    for item in cast(list[object], decoded):
        if not isinstance(item, dict):
            raise RuntimeError(f"{method} {url} returned a non-object array item")
        result.append(cast(dict[str, object], item))
    return result


def _http_get(url: str) -> str:
    _, body = _http_request("GET", url)
    return body


def _http_get_json(url: str) -> dict[str, object]:
    return _http_json("GET", url)


def _derived_password(seed: str, label: str) -> str:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()
    return f"E2e!{digest[:32]}Aa1"


def _handoff() -> tuple[Path, dict[str, object]]:
    state_dir = Path(os.environ.get("E2E_STATE_DIR", "/state"))
    secret_dir = Path(os.environ.get("E2E_SECRET_DIR", "/secrets"))
    return state_dir, _json_object(secret_dir / "platform-controller.json")


_INSTANCE_RECEIPT_KEYS = (
    "instance_id",
    "owner_principal_id",
    "native_identity_id",
    "native_authority_id",
    "workload_authority_id",
)

_active_suite = "system-runner"


def _read_instance_receipt(state_dir: Path) -> dict[str, str] | None:
    path = state_dir / "instance.json"
    if not path.exists():
        return None
    data = _json_object(path)
    return {
        key: _required_string(data, key, "instance claim receipt") for key in _INSTANCE_RECEIPT_KEYS
    }


def _claim_instance(
    control_url: str, login_handle: str, password: str, state_dir: Path
) -> tuple[dict[str, str], SoftwareAuthenticator | None, str | None]:
    """Claim a fresh instance over HTTP and return the built-in authority ids.

    The receipt is cached in the ephemeral state workspace so multi-phase suites
    do not attempt a second claim. If the instance was already claimed elsewhere
    and no local receipt exists, the authority ids cannot be rediscovered and the
    runner fails closed instead of guessing.

    The software passkey is returned only when this invocation performed the
    claim; a resumed phase with a cached receipt returns ``None`` because the
    in-memory key cannot be reconstructed. Callers use it to prove a real
    post-claim WebAuthn login in the same process.
    """
    receipt = _read_instance_receipt(state_dir)
    if receipt is not None:
        return receipt, None, None
    discovery = _http_json("GET", f"{control_url}/v1/setup")
    if discovery.get("setup_required") is not True:
        raise RuntimeError(
            "instance is already claimed but no instance.json receipt exists; "
            "the built-in authority ids cannot be rediscovered"
        )
    session = _http_json("POST", f"{control_url}/v1/setup/sessions", expected_statuses=(201,))
    setup_token = _required_string(session, "token", "setup session response")
    _http_request(
        "POST",
        f"{control_url}/v1/setup/native-identity",
        setup_token=setup_token,
        payload={"login_handle": login_handle, "password": password},
        expected_statuses=(204,),
    )
    options = _http_json(
        "POST",
        f"{control_url}/v1/setup/webauthn/registration-options",
        setup_token=setup_token,
    )
    public_key_value = options.get("public_key")
    if not isinstance(public_key_value, dict):
        raise RuntimeError("setup WebAuthn options are missing public_key")
    public_key = cast(dict[str, object], public_key_value)
    rp_value = public_key.get("rp")
    if not isinstance(rp_value, dict):
        raise RuntimeError("setup WebAuthn options are missing rp")
    rp_id = _required_string(cast(dict[str, object], rp_value), "id", "setup WebAuthn rp")
    challenge = _required_string(public_key, "challenge", "setup WebAuthn challenge")
    authenticator = SoftwareAuthenticator(rp_id=rp_id, origin=f"https://{rp_id}")
    credential = authenticator.registration_credential(
        challenge=websafe_decode(challenge), user_verified=True
    )
    _http_request(
        "POST",
        f"{control_url}/v1/setup/webauthn/registrations",
        setup_token=setup_token,
        payload={"credential": credential},
        expected_statuses=(204,),
    )
    recovery_codes = _http_json(
        "POST",
        f"{control_url}/v1/setup/recovery-codes",
        setup_token=setup_token,
        expected_statuses=(201,),
    )
    raw_codes = recovery_codes.get("codes")
    if not isinstance(raw_codes, list) or not raw_codes or not isinstance(raw_codes[0], str):
        raise RuntimeError("setup recovery-code response did not contain offline codes")
    offline_recovery_code = raw_codes[0]
    finalized = _http_json(
        "POST",
        f"{control_url}/v1/setup:finalize",
        setup_token=setup_token,
        idempotency_key=f"e2e-instance-claim-{_active_suite}",
        payload={"claim_provenance": f"e2e:{_active_suite}"},
        expected_statuses=(201,),
    )
    receipt = {
        "instance_id": _required_string(finalized, "instance_id", "instance claim receipt"),
        "owner_principal_id": _required_string(
            finalized, "owner_principal_id", "instance claim receipt"
        ),
        "native_identity_id": _required_string(
            finalized, "native_identity_id", "instance claim receipt"
        ),
        "native_authority_id": _required_string(
            finalized, "built_in_native_authority_id", "instance claim receipt"
        ),
        "workload_authority_id": _required_string(
            finalized, "built_in_workload_authority_id", "instance claim receipt"
        ),
    }
    path = state_dir / "instance.json"
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return receipt, authenticator, offline_recovery_code


def _assert_runner_isolation(checkpoints: list[dict[str, str]]) -> None:
    forbidden = sorted(
        name
        for name in os.environ
        if any(fragment in name.upper() for fragment in FORBIDDEN_ENV_FRAGMENTS)
    )
    if forbidden:
        raise RuntimeError(
            f"runner received forbidden database/install environment variables: {forbidden}"
        )
    checkpoints.append(
        _checkpoint("runner-env-isolation", "passed", "no database/install DSNs are present")
    )
    if importlib.util.find_spec("request_engine") is not None:
        raise RuntimeError("request_engine is importable inside the black-box runner")
    checkpoints.append(
        _checkpoint("runner-package-isolation", "passed", "request_engine is not installed")
    )
    if Path("/var/run/docker.sock").exists():
        raise RuntimeError("Docker socket is mounted into the black-box runner")
    checkpoints.append(_checkpoint("runner-docker-isolation", "passed", "Docker socket is absent"))
    try:
        socket.getaddrinfo("postgres", 5432)
    except socket.gaierror:
        checkpoints.append(
            _checkpoint(
                "runner-network-isolation",
                "passed",
                "postgres is not resolvable from edge network",
            )
        )
    else:
        raise RuntimeError("postgres unexpectedly resolves from the black-box runner")


def _assert_handoff_contract(checkpoints: list[dict[str, str]], phase: str) -> None:
    state_dir, credentials = _handoff()
    _required_string(credentials, "login_handle", "platform-controller secret")
    password = _required_string(credentials, "password", "platform-controller secret")
    if len(password) < 12:
        raise RuntimeError("platform-controller secret is invalid")
    probe = state_dir / "runner-state-probe.json"
    if phase == "after-fault":
        previous = _json_object(probe)
        if previous.get("phase") != "before-fault":
            raise RuntimeError("runner state did not survive the fault boundary")
    elif phase != "prepare-worker":
        probe.write_text(
            json.dumps({"phase": phase, "written_at": time.time()}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    checkpoints.append(
        _checkpoint(
            f"{phase}:handoff",
            "passed",
            "separated platform-controller secret is available",
        )
    )


def _health_targets(checkpoints: list[dict[str, str]], phase: str) -> None:
    targets = {
        "api-live": "http://api:8000/health/live",
        "api-ready": "http://api:8000/health/ready",
        "control-live": "http://control-plane:8001/health/live",
        "control-ready": "http://control-plane:8001/health/ready",
    }
    for name, url in targets.items():
        body = _http_get(url)
        checkpoints.append(_checkpoint(f"{phase}:{name}", "passed", body[:200]))


def _run_smoke(checkpoints: list[dict[str, str]], phase: str) -> None:
    _health_targets(checkpoints, phase)


def _run_api_restart(checkpoints: list[dict[str, str]], phase: str) -> None:
    api_url = "http://api:8000"
    control_url = "http://control-plane:8001"
    if phase == "before-fault":
        _run_f01_foundation(checkpoints, "main", include_continuity=False)
        state_dir, _ = _handoff()
        receipt = _read_instance_receipt(state_dir)
        if receipt is None:
            raise RuntimeError("instance claim receipt is missing after the F01 foundation")
        foundation, tenant_token = _tenant_session_from_foundation()
        organization_id = _required_string(foundation, "organization_id", "F01 foundation state")
        native_authority_id = receipt["native_authority_id"]
        restart_login = "f01-restart-staff@example.invalid"
        restart_password = _derived_password(
            _required_string(foundation, "tenant_login", "F01 foundation state"),
            "f01-restart-staff",
        )
        restart_identity_id = _native_identity(control_url, restart_login, restart_password)
        invite: dict[str, object] = {
            "identity_authority_id": native_authority_id,
            "native_identity_id": restart_identity_id,
            "provenance_reference": "e2e:f01:api-restart-replay",
        }
        idempotency_key = "f01-api-restart-invite-v1"
        invited = _http_json(
            "POST",
            f"{api_url}/v1/staff/members/native",
            bearer=tenant_token,
            idempotency_key=idempotency_key,
            organization_id=organization_id,
            payload=invite,
            expected_statuses=(201,),
        )
        membership_id = _required_string(invited, "membership_id", "restart invite response")
        principal_id = _required_string(invited, "principal_id", "restart invite response")
        (state_dir / "api-restart.json").write_text(
            json.dumps(
                {
                    "idempotency_key": idempotency_key,
                    "organization_id": organization_id,
                    "membership_id": membership_id,
                    "principal_id": principal_id,
                    "invite": invite,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        checkpoints.append(
            _checkpoint(
                "f01-16-api-restart-prepared",
                "passed",
                "idempotent staff invitation committed before the API fault boundary",
            )
        )
        return
    if phase != "after-fault":
        raise RuntimeError("api-restart requires before-fault or after-fault")
    _health_targets(checkpoints, phase)
    state_dir, _ = _handoff()
    restart = _json_object(state_dir / "api-restart.json")
    foundation, tenant_token = _tenant_session_from_foundation()
    organization_id = _required_string(restart, "organization_id", "api restart state")
    idempotency_key = _required_string(restart, "idempotency_key", "api restart state")
    membership_id = _required_string(restart, "membership_id", "api restart state")
    principal_id = _required_string(restart, "principal_id", "api restart state")
    invite_value = restart.get("invite")
    if not isinstance(invite_value, dict):
        raise RuntimeError("api restart state is missing the invitation payload")
    invite = cast(dict[str, object], invite_value)

    authority = _http_json(
        "GET",
        f"{api_url}/v1/me/authority",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    if authority.get("principal_id") != foundation.get("tenant_controller_principal_id"):
        raise RuntimeError("tenant session identity changed across the API restart")

    replay = _http_json(
        "POST",
        f"{api_url}/v1/staff/members/native",
        bearer=tenant_token,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        payload=invite,
        expected_statuses=(201,),
    )
    if replay.get("membership_id") != membership_id:
        raise RuntimeError("idempotent replay created a different staff membership after restart")

    member = _http_json(
        "GET",
        f"{api_url}/v1/staff/members/{membership_id}",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    if member.get("principal_id") != principal_id:
        raise RuntimeError("replayed staff membership is not the originally committed one")

    page = _http_json(
        "GET",
        f"{api_url}/v1/staff/members",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    items_value = page.get("items")
    if not isinstance(items_value, list):
        raise RuntimeError("staff membership list response is invalid")
    matches: list[dict[str, object]] = []
    for item in cast(list[object], items_value):
        if isinstance(item, dict):
            member_item = cast(dict[str, object], item)
            if member_item.get("membership_id") == membership_id:
                matches.append(member_item)
    if len(matches) != 1:
        raise RuntimeError("idempotent replay produced duplicate staff memberships after restart")

    conflict = _http_json(
        "POST",
        f"{api_url}/v1/staff/members/native",
        bearer=tenant_token,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        payload={
            "identity_authority_id": invite["identity_authority_id"],
            "native_identity_id": invite["native_identity_id"],
            "provenance_reference": "e2e:f01:api-restart-conflicting-intent",
        },
        expected_statuses=(409,),
    )
    if _error_code(conflict, "restart idempotency conflict") != "idempotency_conflict":
        raise RuntimeError("a reused idempotency key with a different intent was not rejected")
    checkpoints.append(
        _checkpoint(
            "f01-17-reconciliation-after-restart",
            "passed",
            "committed command replayed exactly once and key misuse rejected after API restart",
        )
    )


def _run_surface_contract(checkpoints: list[dict[str, str]], phase: str) -> None:
    targets = {
        "api-openapi": "http://api:8000/openapi.json",
        "control-openapi": "http://control-plane:8001/openapi.json",
    }
    for name, url in targets.items():
        document = _http_get_json(url)
        version = document.get("openapi")
        paths_value = document.get("paths")
        if not isinstance(version, str) or not version:
            raise RuntimeError(f"{url} is missing an OpenAPI version")
        if not isinstance(paths_value, dict) or not paths_value:
            raise RuntimeError(f"{url} exposes no OpenAPI paths")
        paths = cast(dict[str, object], paths_value)
        checkpoints.append(
            _checkpoint(f"{phase}:{name}", "passed", f"openapi={version}; paths={len(paths)}")
        )


def _native_session(base_url: str, login: str, password: str) -> str:
    response = _http_json(
        "POST",
        f"{base_url}/auth/native/sessions",
        payload={"login_handle": login, "password": password},
        expected_statuses=(201,),
    )
    return _required_string(response, "access_token", "native session response")


def _native_identity(base_url: str, login: str, password: str) -> str:
    response = _http_json(
        "POST",
        f"{base_url}/auth/native/identities",
        payload={"login_handle": login, "password": password},
        expected_statuses=(201,),
    )
    return _required_string(response, "native_identity_id", "native enrollment response")


def _webauthn_platform_session(
    control_url: str, login_handle: str, authenticator: SoftwareAuthenticator
) -> tuple[str, dict[str, object]]:
    """Authenticate the Platform Owner with the passkey registered during claim.

    Returns the native session token and the trusted session evidence read back
    over HTTP, so the caller can assert the session resolved as
    phishing-resistant with user verification.
    """

    options = _http_json(
        "POST",
        f"{control_url}/auth/native/webauthn/authentication-options",
        payload={"login_handle": login_handle},
    )
    public_key_value = options.get("public_key")
    if not isinstance(public_key_value, dict):
        raise RuntimeError("WebAuthn authentication options are missing public_key")
    public_key = cast(dict[str, object], public_key_value)
    challenge = _required_string(public_key, "challenge", "WebAuthn authentication challenge")
    credential = authenticator.authentication_credential(
        challenge=websafe_decode(challenge), user_verified=True
    )
    created = _http_json(
        "POST",
        f"{control_url}/auth/native/webauthn/sessions",
        payload={"login_handle": login_handle, "credential": credential},
        expected_statuses=(201,),
    )
    token = _required_string(created, "access_token", "WebAuthn native session response")
    evidence = _http_json(
        "GET",
        f"{control_url}/auth/native/sessions/current",
        bearer=token,
    )
    return token, evidence


def _run_f01_foundation(
    checkpoints: list[dict[str, str]], phase: str, *, include_continuity: bool = True
) -> None:
    if phase not in {"main", "prepare-worker"}:
        raise RuntimeError("f01-foundation only supports main or prepare-worker")
    state_dir, controller = _handoff()
    platform_login = _required_string(controller, "login_handle", "platform-controller secret")
    platform_password = _required_string(controller, "password", "platform-controller secret")
    control_url = "http://control-plane:8001"
    api_url = "http://api:8000"

    claim, claim_authenticator, offline_recovery_code = _claim_instance(
        control_url, platform_login, platform_password, state_dir
    )
    native_authority_id = claim["native_authority_id"]
    workload_authority_id = claim["workload_authority_id"]
    checkpoints.append(
        _checkpoint(
            "f01-00-instance-claim",
            "passed",
            "instance claimed over HTTP; built-in authority ids resolved from the claim receipt",
        )
    )

    if claim_authenticator is not None:
        platform_token, evidence = _webauthn_platform_session(
            control_url, platform_login, claim_authenticator
        )
        if evidence.get("authentication_assurance") != "phishing_resistant":
            raise RuntimeError("Platform Owner WebAuthn session is not phishing-resistant")
        if evidence.get("user_verified") is not True:
            raise RuntimeError("Platform Owner WebAuthn session lacks user verification")
        checkpoints.append(
            _checkpoint(
                "f01-01-platform-webauthn-login",
                "passed",
                "platform owner authenticated over TCP with the claim passkey",
            )
        )
    else:
        # Resumed phase with a cached receipt: the in-memory passkey cannot be
        # reconstructed, so reauthenticate through the password path.
        platform_token = _native_session(control_url, platform_login, platform_password)
        checkpoints.append(
            _checkpoint("f01-01-platform-login", "passed", "resumed world password fallback")
        )
    provisioner_login = "f01-security-operator@example.invalid"
    provisioner_password = _derived_password(platform_password, "f01-security-operator")
    provisioner_identity_id = _native_identity(control_url, provisioner_login, provisioner_password)
    provisioner = _http_json(
        "POST",
        f"{control_url}/v1/platform/provisioners",
        bearer=platform_token,
        idempotency_key="f01-platform-provisioner-v1",
        payload={
            "native_identity_id": provisioner_identity_id,
            "provenance_reference": "e2e:f01:second-platform-provisioner",
        },
        expected_statuses=(201,),
    )
    provisioner_principal_id = _required_string(
        provisioner, "principal_id", "platform provisioner response"
    )
    checkpoints.append(_checkpoint("f01-02-second-provisioner", "passed"))

    tenant_login = "f01-tenant-controller@example.invalid"
    tenant_password = _derived_password(platform_password, "f01-tenant-controller")
    tenant_identity_id = _native_identity(control_url, tenant_login, tenant_password)
    organization = _http_json(
        "POST",
        f"{control_url}/v1/platform/organizations",
        bearer=platform_token,
        idempotency_key="f01-organization-v1",
        payload={
            "organization_key": "f01-e2e-organization",
            "display_name": "F01 E2E Organization",
            "controller_native_identity_id": tenant_identity_id,
            "provenance_reference": "e2e:f01:organization-controller",
        },
        expected_statuses=(201,),
    )
    organization_id = _required_string(organization, "organization_id", "organization response")
    organization_party_id = _required_string(
        organization, "organization_party_id", "organization response"
    )
    controller_principal_id = _required_string(
        organization, "controller_principal_id", "organization response"
    )
    controller_binding_id = _required_string(
        organization, "controller_binding_id", "organization response"
    )
    checkpoints.append(_checkpoint("f01-03-organization-controller", "passed"))

    tenant_token = _native_session(api_url, tenant_login, tenant_password)
    authority = _http_json(
        "GET",
        f"{api_url}/v1/me/authority",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    observed_principal_id = _required_string(authority, "principal_id", "self authority response")
    if observed_principal_id != controller_principal_id:
        raise RuntimeError("tenant controller self-authority principal does not match provisioning")
    checkpoints.append(_checkpoint("f01-04-tenant-authority", "passed"))

    expires_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    _http_request(
        "POST",
        f"{api_url}/v1/integrations",
        bearer=tenant_token,
        idempotency_key="f01-invalid-human-integration-v1",
        organization_id=organization_id,
        payload={
            "identity_authority_id": native_authority_id,
            "credential_expires_at": expires_at,
            "provenance_reference": "e2e:f01:reject-human-authority-for-workload",
        },
        expected_statuses=(409,),
    )
    checkpoints.append(
        _checkpoint(
            "f01-05a-workload-authority-boundary",
            "passed",
            "native human authority rejected for integration workload identity",
        )
    )

    integration = _http_json(
        "POST",
        f"{api_url}/v1/integrations",
        bearer=tenant_token,
        idempotency_key="f01-worker-integration-v1",
        organization_id=organization_id,
        payload={
            "identity_authority_id": workload_authority_id,
            "credential_expires_at": expires_at,
            "provenance_reference": "e2e:f01:worker-integration",
        },
        expected_statuses=(201,),
    )
    integration_principal_id = _required_string(
        integration, "principal_id", "integration provision response"
    )
    revision = integration.get("authority_revision")
    if not isinstance(revision, int) or revision < 1:
        raise RuntimeError("integration provision response has invalid authority revision")
    _http_json(
        "POST",
        f"{api_url}/v1/integrations/{integration_principal_id}:activate",
        bearer=tenant_token,
        idempotency_key="f01-worker-integration-activate-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": revision,
            "provenance_reference": "e2e:f01:worker-integration-activate",
        },
    )
    checkpoints.append(_checkpoint("f01-05-integration-principal", "passed"))
    if phase == "main":
        _exercise_staff_zero_authority(
            checkpoints,
            control_url=control_url,
            api_url=api_url,
            tenant_token=tenant_token,
            tenant_password=tenant_password,
            organization_id=organization_id,
            native_authority_id=native_authority_id,
        )
        _exercise_agent_zero_authority(
            checkpoints,
            api_url=api_url,
            tenant_token=tenant_token,
            organization_id=organization_id,
            workload_authority_id=workload_authority_id,
            sponsor_principal_id=controller_principal_id,
            expires_at=expires_at,
        )
        _exercise_integration_revocation(
            checkpoints,
            api_url=api_url,
            tenant_token=tenant_token,
            organization_id=organization_id,
            workload_authority_id=workload_authority_id,
            expires_at=expires_at,
        )
        recovery_login = "f01-recovery-operator@example.invalid"
        recovery_password = _derived_password(platform_password, "f01-recovery-operator")
        recovery_identity_id = _native_identity(control_url, recovery_login, recovery_password)
        recovery_operator = _http_json(
            "POST",
            f"{control_url}/v1/platform/recovery-operators",
            bearer=platform_token,
            idempotency_key="f01-recovery-operator-v1",
            payload={
                "native_identity_id": recovery_identity_id,
                "provenance_reference": "e2e:f01:recovery-operator",
            },
            expected_statuses=(201,),
        )
        _required_string(
            recovery_operator,
            "principal_id",
            "platform recovery operator response",
        )
        checkpoints.append(
            _checkpoint(
                "f01-10b-recovery-operator",
                "passed",
                "bounded platform recovery approver provisioned over HTTP",
            )
        )
        if _active_suite != "recovery-delivery":
            _exercise_recovery_governance(
                checkpoints,
                control_url=control_url,
                api_url=api_url,
                platform_token=platform_token,
                provisioner_login=provisioner_login,
                provisioner_password=provisioner_password,
                recovery_login=recovery_login,
                recovery_password=recovery_password,
                target_native_identity_id=tenant_identity_id,
            )
        if include_continuity:
            _exercise_last_controller_refusal(
                checkpoints,
                api_url=api_url,
                tenant_token=tenant_token,
                organization_id=organization_id,
                controller_binding_id=controller_binding_id,
            )
    foundation = {
        "organization_id": organization_id,
        "organization_party_id": organization_party_id,
        "tenant_controller_principal_id": controller_principal_id,
        "tenant_controller_binding_id": controller_binding_id,
        "platform_provisioner_principal_id": provisioner_principal_id,
        "worker_principal_id": integration_principal_id,
        "tenant_login": tenant_login,
        "tenant_native_identity_id": tenant_identity_id,
    }
    (state_dir / "f01-foundation.json").write_text(
        json.dumps(foundation, sort_keys=True) + "\n", encoding="utf-8"
    )
    checkpoints.append(_checkpoint("f01-foundation-state", "passed"))

    if phase == "main" and offline_recovery_code is not None:
        recovered_password = _derived_password(platform_password, "f01-offline-recovered-owner")
        _http_request(
            "POST",
            f"{control_url}/auth/native/password:recover-with-code",
            payload={
                "recovery_code": offline_recovery_code,
                "new_password": recovered_password,
            },
            expected_statuses=(204,),
        )
        _http_request(
            "POST",
            f"{control_url}/auth/native/sessions",
            payload={"login_handle": platform_login, "password": platform_password},
            expected_statuses=(401,),
        )
        recovered_session = _native_session(
            control_url,
            platform_login,
            recovered_password,
        )
        if not recovered_session:
            raise RuntimeError("offline recovery did not yield a usable replacement password")
        _http_request(
            "POST",
            f"{control_url}/auth/native/password:recover-with-code",
            payload={
                "recovery_code": offline_recovery_code,
                "new_password": _derived_password(recovered_password, "replay"),
            },
            expected_statuses=(401,),
        )
        checkpoints.append(
            _checkpoint(
                "f01-18-offline-owner-recovery",
                "passed",
                "one claim recovery code replaced the owner password over TCP "
                "without reopening setup",
            )
        )


def _exercise_staff_zero_authority(
    checkpoints: list[dict[str, str]],
    *,
    control_url: str,
    api_url: str,
    tenant_token: str,
    tenant_password: str,
    organization_id: str,
    native_authority_id: str,
) -> None:
    staff_login = "f01-bounded-staff@example.invalid"
    staff_password = _derived_password(tenant_password, "f01-bounded-staff")
    staff_identity_id = _native_identity(control_url, staff_login, staff_password)
    invited = _http_json(
        "POST",
        f"{api_url}/v1/staff/members/native",
        bearer=tenant_token,
        idempotency_key="f01-bounded-staff-invite-v1",
        organization_id=organization_id,
        payload={
            "identity_authority_id": native_authority_id,
            "native_identity_id": staff_identity_id,
            "provenance_reference": "e2e:f01:bounded-staff",
        },
        expected_statuses=(201,),
    )
    membership_id = _required_string(invited, "membership_id", "staff invite response")

    activated = _http_json(
        "PUT",
        f"{api_url}/v1/staff/members/{membership_id}/status",
        bearer=tenant_token,
        idempotency_key="f01-bounded-staff-activate-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": "e2e:f01:bounded-staff-activate",
        },
    )
    if activated.get("membership_revision") != 2:
        raise RuntimeError("staff activation did not advance membership revision")

    staff_token = _native_session(api_url, staff_login, staff_password)
    _http_request(
        "GET",
        f"{api_url}/v1/staff/members",
        bearer=staff_token,
        organization_id=organization_id,
        expected_statuses=(403,),
    )
    checkpoints.append(
        _checkpoint(
            "f01-05b-staff-zero-authority",
            "passed",
            "active staff authenticates but receives no implicit staff-management authority",
        )
    )


def _error_code(response: dict[str, object], source: str) -> str:
    error = response.get("error")
    if not isinstance(error, dict):
        raise RuntimeError(f"{source} is missing an error object")
    return _required_string(cast(dict[str, object], error), "code", source)


def _exercise_agent_zero_authority(
    checkpoints: list[dict[str, str]],
    *,
    api_url: str,
    tenant_token: str,
    organization_id: str,
    workload_authority_id: str,
    sponsor_principal_id: str,
    expires_at: str,
) -> None:
    provisioned = _http_json(
        "POST",
        f"{api_url}/v1/agents",
        bearer=tenant_token,
        idempotency_key="f01-bounded-agent-provision-v1",
        organization_id=organization_id,
        payload={
            "identity_authority_id": workload_authority_id,
            "display_name": "F01 Bounded Scheduling Agent",
            "purpose": "prove workload activation without implicit authority",
            "sponsor_principal_id": sponsor_principal_id,
            "operating_mode": "autonomous",
            "credential_expires_at": expires_at,
            "provenance_reference": "e2e:f01:bounded-agent",
        },
        expected_statuses=(201,),
    )
    principal_id = _required_string(provisioned, "principal_id", "agent provision response")
    workload_token = _required_string(provisioned, "workload_token", "agent provision response")
    if provisioned.get("status") != "pending":
        raise RuntimeError("new agent did not start pending")

    lookup_query = urlencode({"mode": "name", "value": "nobody"})
    lookup_url = f"{api_url}/v1/parties/lookup?{lookup_query}"
    pending = _http_json(
        "GET",
        lookup_url,
        bearer=workload_token,
        organization_id=organization_id,
        expected_statuses=(403,),
    )
    pending_code = _error_code(pending, "pending agent lookup")
    if pending_code != "identity_binding_pending":
        raise RuntimeError(f"pending agent was denied for an unexpected reason: {pending_code}")

    activated = _http_json(
        "PUT",
        f"{api_url}/v1/agents/{principal_id}/status",
        bearer=tenant_token,
        idempotency_key="f01-bounded-agent-activate-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": "e2e:f01:bounded-agent-activate",
        },
    )
    if activated.get("profile_revision") != 2:
        raise RuntimeError("agent activation did not advance profile revision")

    active = _http_json(
        "GET",
        lookup_url,
        bearer=workload_token,
        organization_id=organization_id,
        expected_statuses=(403,),
    )
    active_code = _error_code(active, "active zero-authority agent lookup")
    if active_code != "agent_policy_denied":
        raise RuntimeError(f"active agent received unexpected authority outcome: {active_code}")

    checkpoints.append(
        _checkpoint(
            "f01-06-agent-zero-authority",
            "passed",
            "agent workload activates but gains no operational authority implicitly",
        )
    )


def _exercise_integration_revocation(
    checkpoints: list[dict[str, str]],
    *,
    api_url: str,
    tenant_token: str,
    organization_id: str,
    workload_authority_id: str,
    expires_at: str,
) -> None:
    provisioned = _http_json(
        "POST",
        f"{api_url}/v1/integrations",
        bearer=tenant_token,
        idempotency_key="f01-revocable-integration-v1",
        organization_id=organization_id,
        payload={
            "identity_authority_id": workload_authority_id,
            "credential_expires_at": expires_at,
            "provenance_reference": "e2e:f01:revocable-integration",
        },
        expected_statuses=(201,),
    )
    principal_id = _required_string(
        provisioned, "principal_id", "revocable integration provision response"
    )
    workload_token = _required_string(
        provisioned, "workload_token", "revocable integration provision response"
    )
    authority_revision = provisioned.get("authority_revision")
    if not isinstance(authority_revision, int) or authority_revision < 1:
        raise RuntimeError("revocable integration has invalid authority revision")

    assigned = _http_json(
        "PUT",
        f"{api_url}/v1/integrations/{principal_id}/authority",
        bearer=tenant_token,
        idempotency_key="f01-revocable-integration-authority-v1",
        organization_id=organization_id,
        payload={
            "expected_authority_revision": authority_revision,
            "desired_capabilities": ["parties.lookup"],
            "provenance_reference": "e2e:f01:revocable-integration-authority",
        },
    )
    assigned_revision = assigned.get("authority_revision")
    if not isinstance(assigned_revision, int) or assigned_revision <= authority_revision:
        raise RuntimeError("integration authority assignment did not advance revision")

    _http_json(
        "PUT",
        f"{api_url}/v1/integrations/{principal_id}/status",
        bearer=tenant_token,
        idempotency_key="f01-revocable-integration-activate-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": assigned_revision,
            "target_status": "active",
            "provenance_reference": "e2e:f01:revocable-integration-activate",
        },
    )
    lookup_query = urlencode({"mode": "name", "value": "nobody"})
    lookup_url = f"{api_url}/v1/parties/lookup?{lookup_query}"
    _http_request(
        "GET",
        lookup_url,
        bearer=workload_token,
        organization_id=organization_id,
        expected_statuses=(200,),
    )

    current = _http_json(
        "GET",
        f"{api_url}/v1/integrations/{principal_id}",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    current_revision = current.get("authority_revision")
    if not isinstance(current_revision, int) or current_revision < assigned_revision:
        raise RuntimeError("integration read returned invalid authority revision")

    _http_json(
        "PUT",
        f"{api_url}/v1/integrations/{principal_id}/status",
        bearer=tenant_token,
        idempotency_key="f01-revocable-integration-revoke-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": current_revision,
            "target_status": "revoked",
            "provenance_reference": "e2e:f01:revocable-integration-revoke",
        },
    )
    _http_request(
        "GET",
        lookup_url,
        bearer=workload_token,
        organization_id=organization_id,
        expected_statuses=(401,),
    )
    checkpoints.append(
        _checkpoint(
            "f01-10-integration-revocation",
            "passed",
            "revoked workload bearer is rejected immediately through the public API",
        )
    )


def _exercise_recovery_governance(
    checkpoints: list[dict[str, str]],
    *,
    control_url: str,
    api_url: str,
    platform_token: str,
    provisioner_login: str,
    provisioner_password: str,
    recovery_login: str,
    recovery_password: str,
    target_native_identity_id: str,
) -> None:
    case = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases",
        bearer=platform_token,
        idempotency_key="f01-recovery-case-v1",
        payload={
            "target_native_identity_id": target_native_identity_id,
            "reason_code": "lost_credential",
            "evidence_reference": "e2e:f01:recovery-governance",
            "delivery_destination_reference": "e2e-runner@example.invalid",
        },
        expected_statuses=(201,),
    )
    case_id = _required_string(case, "case_id", "recovery case create response")
    if case.get("status") != "requested" or case.get("revision") != 1:
        raise RuntimeError("recovery case did not start requested at revision 1")

    self_approval = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:approve",
        bearer=platform_token,
        idempotency_key="f01-recovery-self-approve-v1",
        payload={"expected_revision": 1, "reason_code": "ownership_verified"},
        expected_statuses=(403,),
    )
    if (
        _error_code(self_approval, "recovery self-approval")
        != "platform_identity_recovery_forbidden"
    ):
        raise RuntimeError("a requester was allowed to approve their own recovery case")

    provisioner_token = _native_session(control_url, provisioner_login, provisioner_password)
    unauthorized = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:approve",
        bearer=provisioner_token,
        idempotency_key="f01-recovery-unauthorized-approve-v1",
        payload={"expected_revision": 1, "reason_code": "ownership_verified"},
        expected_statuses=(403,),
    )
    if (
        _error_code(unauthorized, "recovery unauthorized approval")
        != "platform_identity_recovery_forbidden"
    ):
        raise RuntimeError("a principal without recovery authority approved a case")

    recovery_token = _native_session(control_url, recovery_login, recovery_password)
    _http_request(
        "POST",
        f"{control_url}/v1/platform/organizations",
        bearer=recovery_token,
        idempotency_key="f01-recovery-operator-org-denied-v1",
        payload={
            "organization_key": "forbidden-recovery-operator-org",
            "display_name": "Forbidden recovery operator organization",
            "controller_native_identity_id": target_native_identity_id,
            "provenance_reference": "e2e:f01:recovery-operator-must-not-provision-org",
        },
        expected_statuses=(403,),
    )
    _http_request(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases",
        bearer=recovery_token,
        idempotency_key="f01-recovery-operator-request-denied-v1",
        payload={
            "target_native_identity_id": target_native_identity_id,
            "reason_code": "lost_credential",
            "evidence_reference": "e2e:f01:recovery-operator-no-request",
            "delivery_destination_reference": "e2e-runner@example.invalid",
        },
        expected_statuses=(403,),
    )
    approved = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:approve",
        bearer=recovery_token,
        idempotency_key="f01-recovery-independent-approve-v1",
        payload={"expected_revision": 1, "reason_code": "ownership_verified"},
        expected_statuses=(200,),
    )
    if approved.get("status") != "approved" or approved.get("revision") != 2:
        raise RuntimeError("bounded recovery operator did not approve the requested case")
    checkpoints.append(
        _checkpoint(
            "f01-11a-independent-recovery-approval",
            "passed",
            "distinct bounded recovery operator approved without broader platform authority",
        )
    )

    fail_closed = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:issue",
        bearer=platform_token,
        idempotency_key="f01-recovery-issue-unconfigured-v1",
        payload={"expected_revision": 2},
        expected_statuses=(503,),
    )
    if _error_code(fail_closed, "recovery issue fail-closed") != "recovery_delivery_unconfigured":
        raise RuntimeError("recovery issuance did not fail closed without a delivery channel")

    revoked = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:revoke",
        bearer=platform_token,
        idempotency_key="f01-recovery-revoke-v1",
        payload={"expected_revision": 2, "reason_code": "request_withdrawn"},
    )
    if revoked.get("status") != "revoked":
        raise RuntimeError("recovery case revoke did not reach the revoked state")

    after_revoke = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:approve",
        bearer=platform_token,
        idempotency_key="f01-recovery-approve-after-revoke-v1",
        payload={"expected_revision": 3, "reason_code": "ownership_verified"},
        expected_statuses=(409,),
    )
    if (
        _error_code(after_revoke, "recovery approve after revoke")
        != "platform_identity_recovery_conflict"
    ):
        raise RuntimeError("a revoked recovery case was not refused for approval")

    _http_request(
        "POST",
        f"{api_url}/auth/native/password:recover",
        payload={
            "recovery_token": "e2e-invalid-recovery-proof",
            "new_password": "E2e!InvalidProof123Aa1",
        },
        expected_statuses=(401,),
    )
    checkpoints.append(
        _checkpoint(
            "f01-11-recovery-governance",
            "passed",
            "recovery double-control, fail-closed delivery and consume rejection enforced",
        )
    )


def _exercise_last_controller_refusal(
    checkpoints: list[dict[str, str]],
    *,
    api_url: str,
    tenant_token: str,
    organization_id: str,
    controller_binding_id: str,
) -> None:
    refusal = _http_json(
        "POST",
        f"{api_url}/v1/identity-bindings/{controller_binding_id}:suspend",
        bearer=tenant_token,
        idempotency_key="f01-last-controller-refusal-v1",
        organization_id=organization_id,
        payload={
            "expected_revision": 1,
            "provenance_reference": "e2e:f01:last-controller-refusal",
        },
        expected_statuses=(409,),
    )
    if _error_code(refusal, "last-controller refusal") != "identity_binding_conflict":
        raise RuntimeError("last controller removal was not refused as a continuity conflict")
    checkpoints.append(
        _checkpoint(
            "f01-12-last-controller-refusal",
            "passed",
            "removing the only authenticatable tenant controller is refused over HTTP",
        )
    )


def _tenant_session_from_foundation() -> tuple[dict[str, object], str]:
    state_dir, controller = _handoff()
    foundation = _json_object(state_dir / "f01-foundation.json")
    platform_password = _required_string(controller, "password", "platform-controller secret")
    tenant_login = _required_string(foundation, "tenant_login", "F01 foundation state")
    tenant_password = _derived_password(platform_password, "f01-tenant-controller")
    return foundation, _native_session("http://api:8000", tenant_login, tenant_password)


def _availability_windows() -> list[dict[str, object]]:
    return [
        {"weekday": weekday, "local_start": "08:00:00", "local_end": "18:00:00"}
        for weekday in range(7)
    ]


def _prepare_durable_booking(checkpoints: list[dict[str, str]]) -> None:
    state_dir, _ = _handoff()
    foundation, tenant_token = _tenant_session_from_foundation()
    organization_id = _required_string(foundation, "organization_id", "F01 foundation state")
    authority_party_id = _required_string(
        foundation, "organization_party_id", "F01 foundation state"
    )
    api_url = "http://api:8000"

    location = _http_json(
        "POST",
        f"{api_url}/v1/operations/locations",
        bearer=tenant_token,
        idempotency_key="f01-location-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "location_key": "f01-main-office",
            "display_name": "F01 Main Office",
            "timezone": "UTC",
            "active": True,
        },
        expected_statuses=(200, 201),
    )
    location_id = _required_string(location, "location_id", "location create response")
    revision = location.get("operational_revision")
    if not isinstance(revision, int) or revision < 1:
        raise RuntimeError("location create response has invalid operational revision")
    _http_json(
        "PUT",
        f"{api_url}/v1/operations/locations/{location_id}/hours",
        bearer=tenant_token,
        idempotency_key="f01-location-hours-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "expected_operational_revision": revision,
            "windows": _availability_windows(),
        },
    )

    capability = _http_json(
        "POST",
        f"{api_url}/v1/catalog/resource-capabilities",
        bearer=tenant_token,
        idempotency_key="f01-capability-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "capability_key": "f01-consultation",
            "display_name": "F01 Consultation",
        },
        expected_statuses=(201,),
    )
    capability_id = _required_string(capability, "capability_id", "capability create response")
    offering = _http_json(
        "POST",
        f"{api_url}/v1/catalog/offerings",
        bearer=tenant_token,
        idempotency_key="f01-offering-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "offering_key": "f01-appointment",
            "display_name": "F01 Appointment",
            "duration_minutes": 30,
            "slot_step_minutes": 30,
            "requirements": [{"capability_id": capability_id, "quantity": 1}],
            "reservation_policy": {},
        },
        expected_statuses=(201,),
    )
    offering_version_id = _required_string(
        offering, "offering_version_id", "offering create response"
    )
    resource = _http_json(
        "POST",
        f"{api_url}/v1/booking/resources",
        bearer=tenant_token,
        idempotency_key="f01-resource-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "location_id": location_id,
            "resource_key": "f01-provider",
            "display_name": "F01 Provider",
            "capacity_model": "exclusive",
            "capacity_units": 1,
            "capability_ids": [capability_id],
            "weekly_availability": _availability_windows(),
        },
        expected_statuses=(201,),
    )
    resource_id = _required_string(resource, "resource_id", "resource create response")
    assignment_id = _required_string(
        resource, "resource_location_assignment_id", "resource create response"
    )
    effective_from = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _http_json(
        "POST",
        f"{api_url}/v1/operations/context-terms",
        bearer=tenant_token,
        idempotency_key="f01-context-terms-v1",
        organization_id=organization_id,
        payload={
            "authority_party_id": authority_party_id,
            "resource_location_assignment_id": assignment_id,
            "offering_version_id": offering_version_id,
            "effective_from": effective_from,
            "amount": "50.00",
            "currency": "USD",
            "planned_duration_minutes": 30,
            "bookable": True,
        },
    )
    checkpoints.append(_checkpoint("f01-07-supply-capacity", "passed"))

    target_date = (datetime.now(UTC) + timedelta(days=1)).date()
    window_start = datetime.combine(target_date, datetime_time(8, 0), tzinfo=UTC)
    window_end = datetime.combine(target_date, datetime_time(18, 0), tzinfo=UTC)
    query = urlencode(
        {
            "offering_version_id": offering_version_id,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "location_id": location_id,
            "resource_id": resource_id,
            "limit": 20,
        }
    )
    slots = _http_json_array(
        "GET",
        f"{api_url}/v1/appointments/slots?{query}",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    if not slots:
        raise RuntimeError("configured F01 supply produced no appointment slots")
    option_id = _required_string(slots[0], "option_id", "appointment slot")

    _http_json("POST", "http://event-sink:8090/control/block")
    booking = _http_json(
        "POST",
        f"{api_url}/v1/appointments",
        bearer=tenant_token,
        idempotency_key="f01-reservation-v1",
        organization_id=organization_id,
        payload={"option_id": option_id, "subject_party_id": authority_party_id},
        expected_statuses=(201,),
    )
    reservation_id = _required_string(booking, "id", "reservation response")
    conflict = _http_json(
        "POST",
        f"{api_url}/v1/appointments",
        bearer=tenant_token,
        idempotency_key="f01-reservation-capacity-conflict-v1",
        organization_id=organization_id,
        payload={"option_id": option_id, "subject_party_id": authority_party_id},
        expected_statuses=(409,),
    )
    error_value = conflict.get("error")
    if not isinstance(error_value, dict):
        raise RuntimeError("second booking attempt did not return an error envelope")
    error = cast(dict[str, object], error_value)
    error_code = error.get("code")
    if not isinstance(error_code, str) or error_code not in {
        "appointment_unavailable",
        "appointment_option_stale",
    }:
        raise RuntimeError("second booking attempt did not fail with a capacity-safe conflict")
    checkpoints.append(
        _checkpoint(
            "f01-09-capacity-conflict",
            "passed",
            f"duplicate slot consumption rejected as {error_code}",
        )
    )

    (state_dir / "worker-booking.json").write_text(
        json.dumps(
            {
                "reservation_id": reservation_id,
                "event_type": "reservation.created.v1",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    checkpoints.append(_checkpoint("f01-08-booking-durable-work", "passed", reservation_id))


def _sink_events(path: str) -> list[dict[str, object]]:
    document = _http_get_json(f"http://event-sink:8090/{path}")
    value = document.get(path)
    if not isinstance(value, list):
        raise RuntimeError(f"event sink /{path} response is invalid")
    result: list[dict[str, object]] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            result.append(cast(dict[str, object], item))
    return result


def _matching_sink_event(items: list[dict[str, object]], reservation_id: str) -> bool:
    for item in items:
        event_value = item.get("event") if "event" in item else item
        if not isinstance(event_value, dict):
            continue
        event = cast(dict[str, object], event_value)
        if (
            event.get("event_type") == "reservation.created.v1"
            and event.get("aggregate_id") == reservation_id
        ):
            return True
    return False


def _wait_for_sink_attempt(reservation_id: str, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = _http_get_json("http://event-sink:8090/status")
        attempts = _sink_events("attempts")
        if status.get("blocked") is True and _matching_sink_event(attempts, reservation_id):
            return
        time.sleep(1)
    raise RuntimeError("worker never attempted the blocked durable reservation event")


def _wait_for_sink_delivery(reservation_id: str, timeout_seconds: int = 120) -> None:
    # The outbox lease is 60s. A worker killed while holding the blocked event's
    # lease can only be reclaimed after expiry, so the post-restart wait must
    # exceed one lease plus reclaim/redelivery latency.
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _matching_sink_event(_sink_events("events"), reservation_id):
            return
        time.sleep(1)
    raise RuntimeError("durable reservation event was not delivered after worker restart")


def _run_worker_runtime(checkpoints: list[dict[str, str]], phase: str) -> None:
    if phase == "prepare-worker":
        _run_f01_foundation(checkpoints, phase)
        _prepare_durable_booking(checkpoints)
        return
    if phase not in {"before-fault", "after-fault"}:
        raise RuntimeError("worker-runtime requires prepare-worker/before-fault/after-fault")
    _health_targets(checkpoints, phase)
    state_dir, _ = _handoff()
    foundation = _json_object(state_dir / "f01-foundation.json")
    _required_string(foundation, "worker_principal_id", "F01 foundation state")
    organization_id = _required_string(foundation, "organization_id", "F01 foundation state")
    booking = _json_object(state_dir / "worker-booking.json")
    reservation_id = _required_string(booking, "reservation_id", "worker booking state")
    sink = _http_get_json("http://event-sink:8090/health")
    if sink.get("status") != "ok":
        raise RuntimeError("reference event sink is not healthy")

    if phase == "before-fault":
        _wait_for_sink_attempt(reservation_id)
        status = _http_get_json("http://event-sink:8090/status")
        if status.get("accepted_count") != 0:
            raise RuntimeError("event sink accepted durable work before the worker fault boundary")
        checkpoints.append(
            _checkpoint(
                "f01-13-durable-work-blocked",
                "passed",
                "worker attempted reservation.created.v1 while sink barrier was closed",
            )
        )
        return

    _http_json("POST", "http://event-sink:8090/control/release")
    _wait_for_sink_delivery(reservation_id)
    _, tenant_token = _tenant_session_from_foundation()
    reservation = _http_json(
        "GET",
        f"http://api:8000/v1/appointments/{reservation_id}",
        bearer=tenant_token,
        organization_id=organization_id,
    )
    if _required_string(reservation, "id", "reservation read response") != reservation_id:
        raise RuntimeError("reservation identity changed across worker restart")
    checkpoints.append(
        _checkpoint(
            "f01-15-worker-durable-recovery",
            "passed",
            "reservation event delivered after host-owned worker restart",
        )
    )



def _run_recovery_delivery(checkpoints: list[dict[str, str]], phase: str) -> None:
    if phase == "prepare-worker":
        _run_f01_foundation(checkpoints, phase)
        return
    if phase != "main":
        raise RuntimeError("recovery-delivery requires prepare-worker then main")

    state_dir, controller = _handoff()
    foundation = _json_object(state_dir / "f01-foundation.json")
    control_url = "http://control-plane:8001"
    platform_login = _required_string(
        controller, "login_handle", "platform-controller secret"
    )
    platform_password = _required_string(
        controller, "password", "platform-controller secret"
    )
    target_identity_id = _required_string(
        foundation, "tenant_native_identity_id", "F01 foundation state"
    )
    platform_token = _native_session(control_url, platform_login, platform_password)

    recovery_login = "f01-recovery-operator@example.invalid"
    recovery_password = _derived_password(platform_password, "f01-recovery-operator")
    recovery_operator_token = _native_session(
        control_url, recovery_login, recovery_password
    )

    destination = "e2e-runner@example.invalid"
    case = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases",
        bearer=platform_token,
        idempotency_key="delivery-e2e-recovery-case-v1",
        payload={
            "target_native_identity_id": target_identity_id,
            "reason_code": "lost_credential",
            "evidence_reference": "e2e:recovery-delivery",
            "delivery_destination_reference": destination,
        },
        expected_statuses=(201,),
    )
    case_id = _required_string(case, "case_id", "recovery case create response")
    approved = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:approve",
        bearer=recovery_operator_token,
        idempotency_key="delivery-e2e-recovery-approve-v1",
        payload={"expected_revision": 1, "reason_code": "ownership_verified"},
    )
    if approved.get("status") != "approved" or approved.get("revision") != 2:
        raise RuntimeError("recovery case was not independently approved")

    issued = _http_json(
        "POST",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}:issue",
        bearer=platform_token,
        idempotency_key="delivery-e2e-recovery-issue-v1",
        payload={"expected_revision": 2},
        expected_statuses=(202,),
    )
    if issued.get("status") != "issued":
        raise RuntimeError("configured recovery issuance did not reach issued state")

    deadline = time.monotonic() + 60
    body = ""
    while time.monotonic() < deadline:
        try:
            body = _http_get("http://mailpit:8025/view/latest.txt")
        except (RuntimeError, urllib.error.URLError):
            body = ""
        if "Recovery code: " in body:
            break
        time.sleep(1)
    marker = "Recovery code: "
    if marker not in body:
        raise RuntimeError("Mailpit never received the recovery proof")
    proof = body.split(marker, 1)[1].splitlines()[0].strip()
    if not proof:
        raise RuntimeError("Mailpit recovery message contained an empty proof")

    current = _http_json(
        "GET",
        f"{control_url}/v1/platform/identity-recovery-cases/{case_id}",
        bearer=platform_token,
    )
    if current.get("delivery_status") != "delivered":
        raise RuntimeError("recovery ticket was not finalized as delivered")

    tenant_login = _required_string(foundation, "tenant_login", "F01 foundation state")
    old_password = _derived_password(platform_password, "f01-tenant-controller")
    new_password = _derived_password(platform_password, "recovery-delivery-reset")
    _http_request(
        "POST",
        f"{control_url}/auth/native/password:recover",
        payload={"recovery_token": proof, "new_password": new_password},
        expected_statuses=(204,),
    )
    _http_request(
        "POST",
        f"{control_url}/auth/native/sessions",
        payload={"login_handle": tenant_login, "password": old_password},
        expected_statuses=(401,),
    )
    _native_session(control_url, tenant_login, new_password)
    _http_request(
        "POST",
        f"{control_url}/auth/native/password:recover",
        payload={
            "recovery_token": proof,
            "new_password": _derived_password(new_password, "replay"),
        },
        expected_statuses=(401,),
    )
    checkpoints.append(
        _checkpoint(
            "recovery-delivery-openbao-mailpit",
            "passed",
            "OpenBao staged a one-time proof, worker delivered it through Mailpit, "
            "and the proof rotated the target password exactly once",
        )
    )


Suite = Callable[[list[dict[str, str]], str], None]
SUITES: dict[str, Suite] = {
    "smoke": _run_smoke,
    "surface-contract": _run_surface_contract,
    "api-restart": _run_api_restart,
    "f01-foundation": _run_f01_foundation,
    "worker-runtime": _run_worker_runtime,
    "recovery-delivery": _run_recovery_delivery,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Request Engine generic black-box E2E runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("suite")
    run.add_argument("--phase", default="main")
    run.add_argument("--artifact-dir", default="/artifacts")
    args = parser.parse_args()
    global _active_suite
    _active_suite = args.suite
    checkpoints: list[dict[str, str]] = []
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        _assert_runner_isolation(checkpoints)
        _assert_handoff_contract(checkpoints, args.phase)
        suite = SUITES.get(args.suite)
        if suite is None:
            raise RuntimeError(f"runner does not implement suite selector {args.suite!r}")
        suite(checkpoints, args.phase)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        checkpoints.append(_checkpoint("suite", "failed", str(exc)))
        _write_checkpoints(artifact_dir, checkpoints)
        return 1
    checkpoints.append(_checkpoint("suite", "passed", f"{args.suite}:{args.phase}"))
    _write_checkpoints(artifact_dir, checkpoints)
    return 0


if __name__ == "__main__":
    sys.exit(main())
