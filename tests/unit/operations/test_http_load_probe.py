from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "http_load_probe", ROOT / "scripts/operations/http_load_probe.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/large":
            self.send_response(200)
            self.send_header("Content-Length", "100000000")
            self.end_headers()
            return
        if self.path == "/over-limit":
            body = b"x" * (2 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/slow-body":
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            time.sleep(0.2)
            self.wfile.write(b"ready")
            return
        if self.path == "/delayed-body":
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            time.sleep(0.08)
            self.wfile.write(b"ready")
            return
        if self.path == "/slow-drip":
            self.send_response(200)
            self.send_header("Content-Length", "6")
            self.end_headers()
            for byte in b"abcdef":
                time.sleep(0.03)
                self.wfile.write(bytes((byte,)))
                self.wfile.flush()
            return
        if self.path == "/encoded":
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", "6")
            self.end_headers()
            self.wfile.write(b"opaque")
            return
        time.sleep(0.015)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def do_POST(self) -> None:
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(503)
        self.end_headers()
        self.wfile.write(b"intentionally not recorded")

    def log_message(self, format: str, *args: object) -> None:
        del format
        del args


@pytest.fixture
def local_http_origin() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _plan(origin: str, *, method: str = "GET", path: str = "/health/ready") -> dict[str, Any]:
    return {
        "schema": "request-engine/http-load-plan/v1",
        "mode": "lab",
        "target_origin": origin,
        "allowed_target_origins": [origin],
        "allowed_paths": [path],
        "request": {"method": method, "path": path},
        "total_requests": 12,
        "concurrency": 4,
        "timeout_seconds": 2,
        "max_p95_ms": 1000,
        "max_error_rate": 0.0,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_measures_real_local_http_and_emits_secret_free_evidence(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin)
    result = await module.run_plan(plan)

    assert result["outcome"] == "within_declared_budgets"
    assert result["production_certified"] is False
    assert result["status_counts"] == {"200": 12}
    assert result["latency_ms"]["sample_count"] == 12
    assert result["latency_ms"]["p95"] >= 10
    assert result["error_rate"] == 0
    assert "secret" not in json.dumps(result).lower()
    assert "intentionally not recorded" not in json.dumps(result)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_fails_when_real_http_measurements_exceed_declared_budgets(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin, method="POST", path="/options")
    plan["max_p95_ms"] = 1
    plan["max_error_rate"] = 0

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"503": 12}
    assert result["error_count"] == 12
    assert result["error_rate"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_fails_on_large_advertised_but_truncated_response(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin, path="/large")
    plan["total_requests"] = 1
    plan["max_p95_ms"] = 500

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"transport_error": 1}
    assert result["error_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_fails_when_response_body_exceeds_fixed_cap(local_http_origin: str) -> None:
    plan = _plan(local_http_origin, path="/over-limit")
    plan["total_requests"] = 1
    plan["max_p95_ms"] = 500

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"response_too_large": 1}
    assert result["error_count"] == 1
    assert result["max_response_body_bytes_per_request"] == 1_048_576
    assert result["response_bytes_total"] <= 1_048_576 + 64 * 1024


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_times_out_after_fast_headers_and_slow_body(local_http_origin: str) -> None:
    plan = _plan(local_http_origin, path="/slow-body")
    plan["total_requests"] = 1
    plan["timeout_seconds"] = 0.05
    plan["max_p95_ms"] = 500

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"transport_error": 1}
    assert result["error_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_total_timeout_stops_slow_drip_that_beats_per_read_timeout(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin, path="/slow-drip")
    plan["total_requests"] = 1
    plan["timeout_seconds"] = 0.1
    plan["max_p95_ms"] = 500

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"transport_error": 1}
    assert result["error_count"] == 1
    assert result["latency_ms"]["p95"] < 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_rejects_unexpected_compressed_response(local_http_origin: str) -> None:
    plan = _plan(local_http_origin, path="/encoded")
    plan["total_requests"] = 1

    result = await module.run_plan(plan)

    assert result["outcome"] == "budget_exceeded"
    assert result["status_counts"] == {"unsupported_content_encoding": 1}
    assert result["error_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_latency_includes_delay_after_response_headers(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin, path="/delayed-body")
    plan["total_requests"] = 1
    plan["max_p95_ms"] = 500

    result = await module.run_plan(plan)

    assert result["status_counts"] == {"200": 1}
    assert result["error_count"] == 0
    assert result["response_bytes_total"] == 5
    assert result["latency_ms"]["p95"] >= 70


@pytest.mark.unit
def test_cli_writes_failed_measurement_and_returns_nonzero(
    local_http_origin: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _plan(local_http_origin, method="POST", path="/options")
    plan["max_p95_ms"] = 1
    plan["max_error_rate"] = 0
    plan_path = tmp_path / "plan.json"
    evidence_path = tmp_path / "evidence.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["http_load_probe.py", str(plan_path), "--output", str(evidence_path)],
    )

    assert module.main() == 1
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "budget_exceeded"
    assert evidence["production_certified"] is False
    assert json.loads(capsys.readouterr().out)["error_count"] == 12


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("total_requests", True),
        ("total_requests", 10_001),
        ("concurrency", False),
        ("concurrency", 129),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
        ("timeout_seconds", True),
        ("timeout_seconds", 60.01),
        ("timeout_seconds", 10**400),
        ("max_p95_ms", float("nan")),
        ("max_p95_ms", float("inf")),
        ("max_p95_ms", True),
        ("max_error_rate", float("nan")),
        ("max_error_rate", float("inf")),
        ("max_error_rate", True),
        ("max_error_rate", 1.01),
    ),
)
def test_plan_rejects_non_finite_boolean_and_out_of_range_limits(field: str, value: Any) -> None:
    local_http_origin = "http://127.0.0.1:8000"
    plan = _plan(local_http_origin)
    plan[field] = value

    with pytest.raises(module.LoadProbeError):
        module.validate_plan(plan)


@pytest.mark.unit
def test_plan_requires_exact_origin_and_path_allowlist() -> None:
    local_http_origin = "http://127.0.0.1:8000"
    plan = _plan(local_http_origin)
    plan["target_origin"] = "http://localhost:8123"
    with pytest.raises(module.LoadProbeError, match="exactly match"):
        module.validate_plan(plan)

    plan = _plan(local_http_origin)
    plan["request"]["path"] = "/health/ready/"
    with pytest.raises(module.LoadProbeError, match="allowed_paths"):
        module.validate_plan(plan)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    (
        "/../health",
        "/a/../health",
        "/./health",
        "/a\\..\\health",
        "/%2e%2e/health",
        "/%252e%252e/health",
        "/health\nready",
        "/a//health",
        "/caf\N{LATIN SMALL LETTER E WITH ACUTE}",
    ),
)
def test_plan_rejects_paths_http_clients_may_normalize(path: str) -> None:
    plan = _plan("http://127.0.0.1:8000", path=path)

    with pytest.raises(module.LoadProbeError, match="allowed_paths"):
        module.validate_plan(plan)


@pytest.mark.unit
def test_plan_rejects_malformed_ipv6_origin() -> None:
    plan = _plan("http://[::1")

    with pytest.raises(module.LoadProbeError, match="valid HTTP"):
        module.validate_plan(plan)


@pytest.mark.unit
@pytest.mark.parametrize(
    "header",
    ("Host", "host", "Content-Length", "Transfer-Encoding", "Connection"),
)
def test_plan_rejects_headers_that_can_change_host_or_framing(header: str) -> None:
    plan = _plan("http://127.0.0.1:8000")
    plan["request"]["headers_env"] = {header: "TEST_HEADER_VALUE"}

    with pytest.raises(module.LoadProbeError, match="invalid header"):
        module.validate_plan(plan)


@pytest.mark.unit
def test_plan_rejects_case_insensitive_duplicate_headers() -> None:
    plan = _plan("http://127.0.0.1:8000")
    plan["request"]["headers_env"] = {
        "X-Request-ID": "REQUEST_ID_ONE",
        "x-request-id": "REQUEST_ID_TWO",
    }

    with pytest.raises(module.LoadProbeError, match="invalid header"):
        module.validate_plan(plan)


@pytest.mark.unit
def test_plan_rejects_custom_accept_encoding_header() -> None:
    plan = _plan("http://127.0.0.1:8000")
    plan["request"]["headers_env"] = {"Accept-Encoding": "LOAD_ACCEPT_ENCODING"}

    with pytest.raises(module.LoadProbeError, match="invalid header"):
        module.validate_plan(plan)


@pytest.mark.unit
def test_production_claimed_plan_requires_https() -> None:
    local_http_origin = "http://127.0.0.1:8000"
    plan = _plan(local_http_origin)
    plan["mode"] = "production_claimed"

    with pytest.raises(module.LoadProbeError, match="require HTTPS"):
        module.validate_plan(plan)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sustained_trial_runs_to_deadline_with_bounded_workers(
    local_http_origin: str,
) -> None:
    plan = _plan(local_http_origin)
    plan.update(total_requests=1000, concurrency=2, duration_seconds=1)
    result = await module.run_plan(plan)
    assert result["outcome"] == "within_declared_budgets"
    assert result["duration_completed"] is True
    assert 12 < result["total_requests"] < 1000
    assert result["elapsed_seconds"] >= 1
    assert result["last_request_started_seconds"] >= 0.9
    assert result["peak_active_requests"] == 2
    assert sum(result["status_counts"].values()) == result["total_requests"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_cap_exhaustion_cannot_pass_a_sustained_trial(local_http_origin: str) -> None:
    plan = _plan(local_http_origin)
    plan.update(total_requests=2, concurrency=2, duration_seconds=1)
    result = await module.run_plan(plan)
    assert result["outcome"] == "budget_exceeded"
    assert result["duration_completed"] is False
    assert result["total_requests"] == 2
    assert result["error_rate"] == 0


@pytest.mark.unit
@pytest.mark.parametrize("duration", [True, float("nan"), float("inf"), 0.99, 3601, 10**400])
def test_sustained_duration_is_bounded_and_finite(duration: Any) -> None:
    plan = _plan("http://127.0.0.1:8000")
    plan["duration_seconds"] = duration
    with pytest.raises(module.LoadProbeError, match="duration_seconds"):
        module.validate_plan(plan)


@pytest.mark.unit
def test_request_body_cannot_exceed_byte_cap_with_unicode_expansion() -> None:
    plan = _plan("http://127.0.0.1:8000", method="POST")
    plan["request"]["json_body"] = "é" * (module.MAX_REQUEST_BODY_BYTES // 2)
    with pytest.raises(module.LoadProbeError, match="request cap"):
        module.validate_plan(plan)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_large_environment_header_fails_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan("http://127.0.0.1:1")
    plan["request"]["headers_env"] = {"Authorization": "PROBE_TEST_AUTH"}
    monkeypatch.setenv("PROBE_TEST_AUTH", "s" * module.MAX_HEADER_BYTES)
    with pytest.raises(module.LoadProbeError, match="aggregate cap"):
        await module.run_plan(plan)


@pytest.mark.unit
def test_cli_rejects_oversized_plan_before_json_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "plan.json"
    source.write_bytes(b" " * (module.MAX_PLAN_BYTES + 1))
    monkeypatch.setattr(sys, "argv", ["http_load_probe.py", str(source)])
    with pytest.raises(SystemExit, match="input cap"):
        module.main()
