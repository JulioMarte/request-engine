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
from pathlib import Path
from typing import cast

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
    idempotency_key: str | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
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
        message = f"{method} {url} returned HTTP {exc.code}: {response_body[:300]}"
        raise RuntimeError(message) from exc


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
    bearer: str | None = None,
    idempotency_key: str | None = None,
    expected_statuses: tuple[int, ...] = (200,),
) -> dict[str, object]:
    _, body = _http_request(
        method,
        url,
        payload=payload,
        bearer=bearer,
        idempotency_key=idempotency_key,
        expected_statuses=expected_statuses,
    )
    try:
        decoded: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {url} did not return valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{method} {url} returned a non-object JSON document")
    return cast(dict[str, object], decoded)


def _http_get(url: str) -> str:
    _, body = _http_request("GET", url)
    return body


def _http_get_json(url: str) -> dict[str, object]:
    return _http_json("GET", url)


def _derived_password(seed: str, label: str) -> str:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()
    return f"E2e!{digest[:32]}Aa1"


def _handoff() -> tuple[Path, dict[str, object], dict[str, object]]:
    state_dir = Path(os.environ.get("E2E_STATE_DIR", "/state"))
    secret_dir = Path(os.environ.get("E2E_SECRET_DIR", "/secrets"))
    return (
        state_dir,
        _json_object(state_dir / "bootstrap.json"),
        _json_object(secret_dir / "platform-controller.json"),
    )


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
    state_dir, bootstrap, credentials = _handoff()
    _required_string(bootstrap, "native_authority_id", "bootstrap state")
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
            "bootstrap state and separated controller secret are available",
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
    _health_targets(checkpoints, phase)


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


def _run_f01_foundation(checkpoints: list[dict[str, str]], phase: str) -> None:
    if phase not in {"main", "prepare-worker"}:
        raise RuntimeError("f01-foundation only supports main or prepare-worker")
    state_dir, bootstrap, controller = _handoff()
    native_authority_id = _required_string(bootstrap, "native_authority_id", "bootstrap state")
    platform_login = _required_string(controller, "login_handle", "platform-controller secret")
    platform_password = _required_string(controller, "password", "platform-controller secret")
    control_url = "http://control-plane:8001"
    api_url = "http://api:8000"

    platform_token = _native_session(control_url, platform_login, platform_password)
    checkpoints.append(_checkpoint("f01-01-platform-login", "passed"))
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
    controller_principal_id = _required_string(
        organization, "controller_principal_id", "organization response"
    )
    checkpoints.append(_checkpoint("f01-03-organization-controller", "passed"))

    tenant_token = _native_session(api_url, tenant_login, tenant_password)
    authority = _http_json("GET", f"{api_url}/v1/me/authority", bearer=tenant_token)
    observed_principal_id = _required_string(authority, "principal_id", "self authority response")
    if observed_principal_id != controller_principal_id:
        raise RuntimeError("tenant controller self-authority principal does not match provisioning")
    checkpoints.append(_checkpoint("f01-04-tenant-authority", "passed"))

    expires_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    integration = _http_json(
        "POST",
        f"{api_url}/v1/integrations",
        bearer=tenant_token,
        idempotency_key="f01-worker-integration-v1",
        payload={
            "identity_authority_id": native_authority_id,
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
        payload={
            "expected_revision": revision,
            "provenance_reference": "e2e:f01:worker-integration-activate",
        },
    )
    checkpoints.append(_checkpoint("f01-05-integration-principal", "passed"))
    foundation = {
        "organization_id": organization_id,
        "tenant_controller_principal_id": controller_principal_id,
        "platform_provisioner_principal_id": provisioner_principal_id,
        "worker_principal_id": integration_principal_id,
    }
    (state_dir / "f01-foundation.json").write_text(
        json.dumps(foundation, sort_keys=True) + "\n", encoding="utf-8"
    )
    checkpoints.append(_checkpoint("f01-foundation-state", "passed"))


def _run_worker_runtime(checkpoints: list[dict[str, str]], phase: str) -> None:
    if phase == "prepare-worker":
        _run_f01_foundation(checkpoints, phase)
        return
    if phase not in {"before-fault", "after-fault"}:
        raise RuntimeError("worker-runtime requires prepare-worker/before-fault/after-fault")
    _health_targets(checkpoints, phase)
    state_dir, _, _ = _handoff()
    foundation = _json_object(state_dir / "f01-foundation.json")
    _required_string(foundation, "worker_principal_id", "F01 foundation state")
    sink = _http_get_json("http://event-sink:8090/health")
    if sink.get("status") != "ok":
        raise RuntimeError("reference event sink is not healthy")
    checkpoints.append(
        _checkpoint(f"{phase}:worker-runtime", "passed", "worker topology observable")
    )


Suite = Callable[[list[dict[str, str]], str], None]
SUITES: dict[str, Suite] = {
    "smoke": _run_smoke,
    "surface-contract": _run_surface_contract,
    "api-restart": _run_api_restart,
    "f01-foundation": _run_f01_foundation,
    "worker-runtime": _run_worker_runtime,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Request Engine generic black-box E2E runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("suite")
    run.add_argument("--phase", default="main")
    run.add_argument("--artifact-dir", default="/artifacts")
    args = parser.parse_args()
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
