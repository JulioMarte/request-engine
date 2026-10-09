#!/usr/bin/env python3
"""Run a bounded, explicitly allowlisted HTTP load measurement."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

MAX_RESPONSE_BODY_BYTES = 1_048_576
RESPONSE_CHUNK_BYTES = 64 * 1024


class LoadProbeError(ValueError):
    """The load plan is invalid or the probe could not be executed safely."""


class ResponseBodyTooLarge(Exception):
    """A response exceeded the probe's bounded-drain limit."""


class ResponseEncodingUnsupported(Exception):
    """A response requested automatic decompression or encoded-body handling."""


def _finite_number(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LoadProbeError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise LoadProbeError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise LoadProbeError(f"{label} must be between {minimum} and {maximum}")
    return number


def _validate_origin(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LoadProbeError(f"{label} must be an exact HTTP(S) origin")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise LoadProbeError(f"{label} must be a valid HTTP(S) origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LoadProbeError(f"{label} must be an exact HTTP(S) origin without credentials or path")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise LoadProbeError(f"{label} has an invalid port") from exc
    # Canonicalize only the optional trailing slash; do not broaden host matching.
    return value.rstrip("/")


def _validate_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return False
    if "\\" in value or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return False
    # Percent encoding and non-ASCII are intentionally disallowed: HTTP clients and
    # intermediaries can decode or normalize them before route matching.
    if not value.isascii() or "%" in value or "?" in value or "#" in value or "//" in value:
        return False
    if not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@/-]*", value):
        return False
    return all(segment not in {".", ".."} for segment in value.split("/"))


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise LoadProbeError("plan must be a JSON object")
    typed_plan = cast(dict[str, Any], plan)
    if typed_plan.get("schema") != "request-engine/http-load-plan/v1":
        raise LoadProbeError("unsupported plan schema")
    mode = typed_plan.get("mode")
    if mode not in {"lab", "production_claimed"}:
        raise LoadProbeError("mode must be lab or production_claimed")

    origin = _validate_origin(typed_plan.get("target_origin"), "target_origin")
    allowed_origins = typed_plan.get("allowed_target_origins")
    if not isinstance(allowed_origins, list) or not allowed_origins:
        raise LoadProbeError("allowed_target_origins must be a non-empty exact allowlist")
    allowed_origin_values = cast(list[Any], allowed_origins)
    normalized_origins: list[str] = [
        _validate_origin(item, "allowed_target_origins entry") for item in allowed_origin_values
    ]
    if len(set(normalized_origins)) != len(normalized_origins) or origin not in normalized_origins:
        raise LoadProbeError("target_origin must exactly match one allowed_target_origins entry")
    if mode == "production_claimed" and not origin.startswith("https://"):
        raise LoadProbeError(
            "production_claimed targets require HTTPS with certificate verification"
        )

    request = typed_plan.get("request")
    if not isinstance(request, dict):
        raise LoadProbeError("request must be an object")
    request_values = cast(dict[str, Any], request)
    method = request_values.get("method")
    if method not in {"GET", "POST"}:
        raise LoadProbeError("request.method must be GET or POST")
    path = request_values.get("path")
    allow_paths = typed_plan.get("allowed_paths")
    allow_path_values = cast(list[Any], allow_paths) if isinstance(allow_paths, list) else []
    if (
        not _validate_path(path)
        or not isinstance(allow_paths, list)
        or not allow_paths
        or any(not _validate_path(item) for item in allow_path_values)
        or len(set(allow_path_values)) != len(allow_path_values)
        or path not in allow_path_values
    ):
        raise LoadProbeError("request.path must exactly match an allowed_paths entry")
    body = request_values.get("json_body")
    if method == "GET" and body is not None:
        raise LoadProbeError("GET requests cannot include json_body")
    if body is not None and not isinstance(body, (dict, list, str, int, float, bool)):
        raise LoadProbeError("request.json_body must be JSON serializable")
    try:
        json.dumps(body, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LoadProbeError("request.json_body must be valid finite JSON") from exc

    headers_env = request_values.get("headers_env", {})
    if not isinstance(headers_env, dict):
        raise LoadProbeError(
            "request.headers_env must map header names to environment variable names"
        )
    header_env_values = cast(dict[Any, Any], headers_env)
    forbidden_headers = {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "accept-encoding",
    }
    normalized_headers: set[str] = set()
    for header, env_name in header_env_values.items():
        if (
            not isinstance(header, str)
            or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header)
            or header.lower() in forbidden_headers
            or header.lower() in normalized_headers
            or not isinstance(env_name, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", env_name)
        ):
            raise LoadProbeError(
                "request.headers_env contains an invalid header or environment reference"
            )
        normalized_headers.add(header.lower())

    count = typed_plan.get("total_requests")
    concurrency = typed_plan.get("concurrency")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10_000:
        raise LoadProbeError("total_requests must be an integer from 1 through 10000")
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not 1 <= concurrency <= 128
    ):
        raise LoadProbeError("concurrency must be an integer from 1 through 128")
    timeout = _finite_number(
        typed_plan.get("timeout_seconds"), "timeout_seconds", minimum=0.001, maximum=60
    )
    max_p95 = _finite_number(
        typed_plan.get("max_p95_ms"), "max_p95_ms", minimum=0, maximum=3_600_000
    )
    max_error = _finite_number(
        typed_plan.get("max_error_rate"), "max_error_rate", minimum=0, maximum=1
    )
    return {
        "schema": typed_plan["schema"],
        "mode": mode,
        "target_origin": origin,
        "allowed_target_origins": normalized_origins,
        "allowed_paths": list(allow_path_values),
        "request": {
            "method": method,
            "path": path,
            "json_body": body,
            "headers_env": dict(header_env_values),
        },
        "total_requests": count,
        "concurrency": concurrency,
        "timeout_seconds": timeout,
        "max_p95_ms": max_p95,
        "max_error_rate": max_error,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


async def run_plan(plan: Any) -> dict[str, Any]:
    config = validate_plan(plan)
    request_config = cast(dict[str, Any], config["request"])
    headers: dict[str, str] = {}
    for header, env_name in request_config["headers_env"].items():
        value = os.environ.get(env_name)
        if value is None:
            raise LoadProbeError(f"environment variable referenced by header {header} is missing")
        headers[header] = value
    headers["Accept-Encoding"] = "identity"

    url = f"{config['target_origin']}{request_config['path']}"
    latencies: list[float] = []
    status_counts: Counter[str] = Counter()
    error_count = 0
    response_bytes_total = 0
    semaphore = asyncio.Semaphore(config["concurrency"])
    timeout = httpx.Timeout(config["timeout_seconds"])
    limits = httpx.Limits(
        max_connections=config["concurrency"],
        max_keepalive_connections=config["concurrency"],
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
        verify=True,
        trust_env=False,
    ) as client:

        async def one_request() -> None:
            nonlocal error_count, response_bytes_total
            async with semaphore:
                started = time.perf_counter()
                body_bytes = 0
                try:
                    async with asyncio.timeout(config["timeout_seconds"]):
                        async with client.stream(
                            request_config["method"],
                            url,
                            headers=headers,
                            json=request_config["json_body"],
                        ) as response:
                            status_code = response.status_code
                            content_encoding = response.headers.get("content-encoding", "identity")
                            if content_encoding.strip().lower() not in {"", "identity"}:
                                raise ResponseEncodingUnsupported
                            async for chunk in response.aiter_raw(chunk_size=RESPONSE_CHUNK_BYTES):
                                body_bytes += len(chunk)
                                response_bytes_total += len(chunk)
                                if body_bytes > MAX_RESPONSE_BODY_BYTES:
                                    raise ResponseBodyTooLarge
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies.append(elapsed_ms)
                    status_counts[str(status_code)] += 1
                    if status_code >= 300:
                        error_count += 1
                except ResponseBodyTooLarge:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies.append(elapsed_ms)
                    status_counts["response_too_large"] += 1
                    error_count += 1
                except ResponseEncodingUnsupported:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies.append(elapsed_ms)
                    status_counts["unsupported_content_encoding"] += 1
                    error_count += 1
                except (httpx.HTTPError, TimeoutError):
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies.append(elapsed_ms)
                    status_counts["transport_error"] += 1
                    error_count += 1

        started = time.perf_counter()
        await asyncio.gather(*(one_request() for _ in range(config["total_requests"])))
        elapsed_seconds = time.perf_counter() - started

    error_rate = error_count / config["total_requests"]
    p95 = _percentile(latencies, 0.95)
    passed = (
        p95 is not None and p95 <= config["max_p95_ms"] and error_rate <= config["max_error_rate"]
    )
    return {
        "schema": "request-engine/http-load-evidence/v1",
        "mode": config["mode"],
        "production_certified": False,
        "outcome": "within_declared_budgets" if passed else "budget_exceeded",
        "measured_at": datetime.now(UTC).isoformat(),
        "target_origin": config["target_origin"],
        "path": request_config["path"],
        "method": request_config["method"],
        "total_requests": config["total_requests"],
        "concurrency": config["concurrency"],
        "timeout_seconds": config["timeout_seconds"],
        "elapsed_seconds": elapsed_seconds,
        "status_counts": dict(sorted(status_counts.items())),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": p95,
            "p99": _percentile(latencies, 0.99),
            "sample_count": len(latencies),
        },
        "error_count": error_count,
        "error_rate": error_rate,
        "response_bytes_total": response_bytes_total,
        "max_response_body_bytes_per_request": MAX_RESPONSE_BODY_BYTES,
        "declared_budgets": {
            "max_p95_ms": config["max_p95_ms"],
            "max_error_rate": config["max_error_rate"],
        },
        "sensitive_header_or_request_body_values_recorded": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plan", type=Path, help="JSON plan with exact origin/path allowlists and budgets"
    )
    parser.add_argument("--output", type=Path, help="write evidence JSON to this path")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        evidence = asyncio.run(run_plan(plan))
    except (OSError, json.JSONDecodeError, LoadProbeError) as exc:
        raise SystemExit(f"HTTP load probe failed: {exc}") from exc
    rendered = json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if evidence["outcome"] == "within_declared_budgets" else 1


if __name__ == "__main__":
    raise SystemExit(main())
