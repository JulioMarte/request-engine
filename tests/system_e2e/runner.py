from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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


def _http_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}: {body[:200]}")
        return body


def _http_get_json(url: str) -> dict[str, object]:
    body = _http_get(url)
    try:
        decoded: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} did not return valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{url} returned a non-object JSON document")
    return cast(dict[str, object], decoded)


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
        _checkpoint(
            "runner-env-isolation",
            "passed",
            "no database/install DSNs are present",
        )
    )

    if importlib.util.find_spec("request_engine") is not None:
        raise RuntimeError("request_engine is importable inside the black-box runner")
    checkpoints.append(
        _checkpoint(
            "runner-package-isolation",
            "passed",
            "request_engine is not installed",
        )
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


def _run_smoke(checkpoints: list[dict[str, str]]) -> None:
    targets = {
        "api-live": "http://api:8000/health/live",
        "api-ready": "http://api:8000/health/ready",
        "control-live": "http://control-plane:8001/health/live",
        "control-ready": "http://control-plane:8001/health/ready",
    }
    for name, url in targets.items():
        body = _http_get(url)
        checkpoints.append(_checkpoint(name, "passed", body[:200]))


def _run_surface_contract(checkpoints: list[dict[str, str]]) -> None:
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
            _checkpoint(
                name,
                "passed",
                f"openapi={version}; paths={len(paths)}",
            )
        )


SUITES: dict[str, Callable[[list[dict[str, str]]], None]] = {
    "smoke": _run_smoke,
    "surface-contract": _run_surface_contract,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Request Engine generic black-box E2E runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("suite")
    run.add_argument("--artifact-dir", default="/artifacts")
    args = parser.parse_args()

    checkpoints: list[dict[str, str]] = []
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    try:
        _assert_runner_isolation(checkpoints)
        suite = SUITES.get(args.suite)
        if suite is None:
            raise RuntimeError(f"runner does not implement suite selector {args.suite!r}")
        suite(checkpoints)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        checkpoints.append(_checkpoint("suite", "failed", str(exc)))
        _write_checkpoints(artifact_dir, checkpoints)
        return 1

    checkpoints.append(_checkpoint("suite", "passed", args.suite))
    _write_checkpoints(artifact_dir, checkpoints)
    return 0


if __name__ == "__main__":
    sys.exit(main())
