#!/usr/bin/env python3
"""Run bounded black-box HTTPS and network-isolation checks from a lab client.

This executable is intended for an orchestrator-owned client container. It has
no database, Docker, or application credentials. Its JSON output contains only
target identifiers, HTTP status codes, and transport observations.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import math
import socket
import ssl
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SCHEMA = "request-engine/network-auth-plan/v1"
MAX_PLAN_BYTES = 65_536
MAX_BLOCKED_ENDPOINTS = 16
MAX_ADMISSION_REQUESTS = 16
MAX_REACHABLE_ENDPOINTS = 16
MAX_RESPONSE_BYTES = 65_536
HEALTH_PATH = "/health/ready"
ADMISSION_PATH = "/auth/native/webauthn/authentication-options"
ADMISSION_LOGIN_HANDLE = "lab-admission@example.invalid"


class ProbeError(ValueError):
    """The plan is unsafe, or a required positive/negative proof failed."""


def _origin(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProbeError(f"{label} must be an exact HTTPS origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ProbeError(f"{label} must be a valid HTTPS origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeError(f"{label} must be an exact HTTPS origin without credentials or path")
    if port is not None and not 1 <= port <= 65535:
        raise ProbeError(f"{label} has an invalid port")
    return value.rstrip("/")


def _positive_timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeError("timeout_seconds must be finite and between 0.1 and 10")
    try:
        parsed = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProbeError("timeout_seconds must be finite and between 0.1 and 10") from exc
    if not math.isfinite(parsed) or not 0.1 <= parsed <= 10:
        raise ProbeError("timeout_seconds must be finite and between 0.1 and 10")
    return parsed


def _validate_tcp_endpoints(raw: Any, label: str) -> list[dict[str, Any]]:
    maximum = MAX_BLOCKED_ENDPOINTS if label == "blocked" else MAX_REACHABLE_ENDPOINTS
    if not isinstance(raw, list):
        raise ProbeError(f"{label}_endpoints must contain 1 to {maximum} endpoints")
    items = cast(list[Any], raw)
    if not 1 <= len(items) <= maximum:
        raise ProbeError(f"{label}_endpoints must contain 1 to {maximum} endpoints")
    endpoints: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ProbeError(f"{label} endpoint must be an object")
        endpoint = cast(dict[str, Any], item)
        identifier = endpoint.get("id")
        address = endpoint.get("address")
        port = endpoint.get("port")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 64:
            raise ProbeError(f"{label} endpoint id must be bounded nonempty text")
        if identifier in identifiers:
            raise ProbeError(f"{label} endpoint ids must be unique")
        identifiers.add(identifier)
        if not isinstance(address, str):
            raise ProbeError(f"{label} endpoint address must be an IP literal")
        try:
            ipaddress.ip_address(address)
        except ValueError as exc:
            raise ProbeError(f"{label} endpoint address must be an IP literal") from exc
        if type(port) is not int or not 1 <= port <= 65535:
            raise ProbeError(f"{label} endpoint port must be an integer from 1 to 65535")
        endpoints.append({"id": identifier, "address": address, "port": port})
    return endpoints


def _validate_admission_plan(plan: dict[str, Any], timeout: float) -> dict[str, Any]:
    targets = plan.get("targets")
    if not isinstance(targets, dict):
        raise ProbeError("admission targets must declare exactly api and replica origins")
    target_values = cast(dict[str, Any], targets)
    if set(target_values) != {"api", "replica"}:
        raise ProbeError("admission targets must declare exactly api and replica origins")
    normalized_targets = {
        key: _origin(value, f"targets.{key}") for key, value in target_values.items()
    }
    requests = plan.get("requests")
    if not isinstance(requests, list):
        raise ProbeError(f"requests must contain 1 to {MAX_ADMISSION_REQUESTS} calls")
    request_values = cast(list[Any], requests)
    if not 1 <= len(request_values) <= MAX_ADMISSION_REQUESTS:
        raise ProbeError(f"requests must contain 1 to {MAX_ADMISSION_REQUESTS} calls")
    validated_calls: list[dict[str, Any]] = []
    for item in request_values:
        if not isinstance(item, dict):
            raise ProbeError("admission call must be an object")
        call = cast(dict[str, Any], item)
        target = call.get("target")
        expected = call.get("expected_status")
        if not isinstance(target, str) or target not in normalized_targets:
            raise ProbeError("admission target must be api or replica")
        if type(expected) is not int or expected not in {200, 429}:
            raise ProbeError("expected_status must be 200 or 429")
        validated_calls.append({"target": target, "expected_status": expected})
    return {
        "schema": SCHEMA,
        "role": "admission",
        "timeout_seconds": timeout,
        "targets": normalized_targets,
        "requests": validated_calls,
    }


def validate_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ProbeError("plan must be a JSON object")
    plan = cast(dict[str, Any], raw)
    if plan.get("schema") != SCHEMA:
        raise ProbeError("unsupported network-auth plan schema")
    role = plan.get("role")
    if not isinstance(role, str) or role not in {"public", "private", "admission"}:
        raise ProbeError("role must be public, private, or admission")
    timeout = _positive_timeout(plan.get("timeout_seconds", 3))

    if role in {"public", "private"}:
        key = "api_origin" if role == "public" else "control_origin"
        origin = _origin(plan.get(key), key)
        result: dict[str, Any] = {
            "schema": SCHEMA,
            "role": role,
            key: origin,
            "timeout_seconds": timeout,
        }
        if role == "public":
            result["blocked_endpoints"] = _validate_tcp_endpoints(
                plan.get("blocked_endpoints"), "blocked"
            )
        else:
            result["reachable_endpoints"] = _validate_tcp_endpoints(
                plan.get("reachable_endpoints"), "reachable"
            )
        return result
    return _validate_admission_plan(plan, timeout)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        return None


def _https_status(
    context: ssl.SSLContext, origin: str, path: str, timeout: float, *, post_json: bool = False
) -> int:
    body = (
        json.dumps({"login_handle": ADMISSION_LOGIN_HANDLE}).encode("utf-8") if post_json else None
    )
    headers = {"Accept": "application/json"}
    if post_json:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{origin}{path}", data=body, headers=headers, method="POST" if post_json else "GET"
    )
    opener = build_opener(HTTPSHandler(context=context), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(MAX_RESPONSE_BYTES + 1)
            return response.status
    except HTTPError as exc:
        exc.read(MAX_RESPONSE_BYTES + 1)
        return exc.code
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        # TLS verification errors and transport errors are positive-check failures;
        # callers never reinterpret them as evidence that a private listener is blocked.
        raise ProbeError(f"verified HTTPS request failed: {type(exc).__name__}") from exc


def _run_boundary_plan(
    plan: dict[str, Any], context: ssl.SSLContext, timeout: float
) -> list[dict[str, Any]]:
    is_public = plan["role"] == "public"
    origin_key = "api_origin" if is_public else "control_origin"
    label = "public_api_https" if is_public else "private_control_https"
    status = _https_status(context, plan[origin_key], HEALTH_PATH, timeout)
    if status != 200:
        raise ProbeError(f"{label} expected HTTP 200, received {status}")
    results: list[dict[str, Any]] = [
        {"id": label, "status": status, "tls_verified": True, "expectation_met": True}
    ]
    endpoint_key = "blocked_endpoints" if is_public else "reachable_endpoints"
    endpoints = plan[endpoint_key]
    for endpoint in endpoints:
        observation = "transport_error"
        connected = False
        try:
            with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=timeout):
                connected = True
                observation = "reachable"
        except ConnectionRefusedError:
            observation = "refused"
        except TimeoutError:
            observation = "timeout"
        except OSError as exc:
            observation = (
                "no_route"
                if is_public and exc.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH}
                else "transport_error"
            )
        matched = connected
        if is_public:
            matched = not connected and observation in {"refused", "timeout", "no_route"}
        results.append(
            {
                "id": endpoint["id"],
                "address": endpoint["address"],
                "port": endpoint["port"],
                "observation": observation,
                "tcp_connected": connected,
                "expectation_met": matched,
            }
        )
        if not matched:
            expectation = "blocked" if is_public else "reachable"
            raise ProbeError(f"{expectation} TCP endpoint {endpoint['id']} was {observation}")
    return results


def _run_admission_plan(
    plan: dict[str, Any], context: ssl.SSLContext, timeout: float
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, call in enumerate(plan["requests"]):
        status = _https_status(
            context,
            plan["targets"][call["target"]],
            ADMISSION_PATH,
            timeout,
            post_json=True,
        )
        matched = status == call["expected_status"]
        results.append(
            {
                "id": f"admission_call_{index + 1}",
                "target": call["target"],
                "status": status,
                "expected_status": call["expected_status"],
                "tls_verified": True,
                "expectation_met": matched,
            }
        )
        if not matched:
            raise ProbeError(
                f"admission call {index + 1} via {call['target']} expected "
                f"HTTP {call['expected_status']}, received {status}"
            )
    return results


def _verify_private_baseline(endpoints: list[dict[str, Any]], baseline: Any) -> None:
    if not isinstance(baseline, dict):
        raise ProbeError("public checks require a successful private TCP baseline")
    evidence = cast(dict[str, Any], baseline)
    if (
        evidence.get("schema") != "request-engine/network-auth-evidence/v1"
        or evidence.get("role") != "private"
        or evidence.get("outcome") != "expectations_met"
    ):
        raise ProbeError("public checks require a successful private TCP baseline")
    results = evidence.get("results")
    if not isinstance(results, list):
        raise ProbeError("private baseline is missing endpoint evidence")
    result_values = cast(list[Any], results)
    if not result_values or not isinstance(result_values[0], dict):
        raise ProbeError("private baseline is missing its verified HTTPS check")
    positive_https = cast(dict[str, Any], result_values[0])
    if (
        positive_https.get("id") != "private_control_https"
        or positive_https.get("status") != 200
        or positive_https.get("tls_verified") is not True
    ):
        raise ProbeError("private baseline lacks a verified control HTTPS check")
    endpoint_results = [
        cast(dict[str, Any], item) for item in result_values[1:] if isinstance(item, dict)
    ]
    for endpoint in endpoints:
        if not any(
            result.get("id") == endpoint["id"]
            and result.get("address") == endpoint["address"]
            and result.get("port") == endpoint["port"]
            and result.get("tcp_connected") is True
            and result.get("expectation_met") is True
            for result in endpoint_results
        ):
            raise ProbeError(f"private baseline did not reach exact endpoint {endpoint['id']}")


def run_plan(raw: Any, *, ca_file: Path, private_baseline: Any = None) -> dict[str, Any]:
    plan = validate_plan(raw)
    if plan["role"] == "public":
        _verify_private_baseline(plan["blocked_endpoints"], private_baseline)
    try:
        context = ssl.create_default_context(cafile=str(ca_file))
    except (OSError, ssl.SSLError) as exc:
        raise ProbeError("laboratory CA could not be loaded") from exc
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    timeout = plan["timeout_seconds"]
    started = time.monotonic()
    if plan["role"] == "admission":
        results = _run_admission_plan(plan, context, timeout)
    else:
        results = _run_boundary_plan(plan, context, timeout)

    evidence = {
        "schema": "request-engine/network-auth-evidence/v1",
        "role": plan["role"],
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "results": results,
        "outcome": "expectations_met",
        "production_certified": False,
    }
    if plan["role"] == "public":
        evidence["private_baseline_verified"] = True
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--private-baseline", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        with args.plan.open("rb") as stream:
            raw = stream.read(MAX_PLAN_BYTES + 1)
        if len(raw) > MAX_PLAN_BYTES:
            raise ProbeError("plan exceeds the 64 KiB input cap")
        private_baseline: Any = None
        if args.private_baseline is not None:
            with args.private_baseline.open("rb") as stream:
                baseline_raw = stream.read(MAX_PLAN_BYTES + 1)
            if len(baseline_raw) > MAX_PLAN_BYTES:
                raise ProbeError("private baseline exceeds the 64 KiB input cap")
            private_baseline = json.loads(baseline_raw)
        evidence = run_plan(
            json.loads(raw), ca_file=args.ca_file, private_baseline=private_baseline
        )
    except (ProbeError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Network/auth probe failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
