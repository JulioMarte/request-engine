from __future__ import annotations

import errno
import importlib.util
import ssl
from pathlib import Path
from typing import Any

import pytest

PROBE_PATH = Path(__file__).resolve().parents[2] / "system_e2e/network_boundary_probe.py"
SPEC = importlib.util.spec_from_file_location("network_boundary_probe", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def _context(monkeypatch: pytest.MonkeyPatch) -> None:
    def make_context(*, cafile: str | None = None) -> ssl.SSLContext:
        del cafile
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def successful_status(
        _context: ssl.SSLContext,
        _origin: str,
        _path: str,
        _timeout: float,
        *,
        post_json: bool = False,
    ) -> int:
        del post_json
        return 200

    monkeypatch.setattr(
        probe.ssl,
        "create_default_context",
        make_context,
    )
    monkeypatch.setattr(probe, "_https_status", successful_status)


def _public_plan() -> dict[str, Any]:
    return {
        "schema": probe.SCHEMA,
        "role": "public",
        "api_origin": "https://api-lab",
        "timeout_seconds": 1,
        "blocked_endpoints": [
            {"id": "control", "address": "10.20.0.4", "port": 8443},
            {"id": "postgres", "address": "10.20.0.5", "port": 5432},
        ],
    }


def _private_plan() -> dict[str, Any]:
    return {
        "schema": probe.SCHEMA,
        "role": "private",
        "control_origin": "https://control-lab",
        "timeout_seconds": 1,
        "reachable_endpoints": [
            {"id": "postgres", "address": "10.20.0.5", "port": 5432},
            {"id": "openbao", "address": "10.20.0.6", "port": 8200},
        ],
    }


def _private_baseline() -> dict[str, Any]:
    results: list[dict[str, Any]] = [
        {
            "id": "private_control_https",
            "status": 200,
            "tls_verified": True,
            "expectation_met": True,
        }
    ]
    for endpoint in _public_plan()["blocked_endpoints"]:
        results.append(
            {
                **endpoint,
                "observation": "reachable",
                "tcp_connected": True,
                "expectation_met": True,
            }
        )
    return {
        "schema": "request-engine/network-auth-evidence/v1",
        "role": "private",
        "results": results,
        "outcome": "expectations_met",
    }


def test_public_requires_verified_https_and_blocked_raw_tcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    def timeout_connection(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        raise TimeoutError()

    monkeypatch.setattr(
        probe.socket,
        "create_connection",
        timeout_connection,
    )

    evidence = probe.run_plan(
        _public_plan(), ca_file=tmp_path / "ca.crt", private_baseline=_private_baseline()
    )

    assert evidence["outcome"] == "expectations_met"
    assert evidence["results"][0] == {
        "id": "public_api_https",
        "status": 200,
        "tls_verified": True,
        "expectation_met": True,
    }
    assert [item["observation"] for item in evidence["results"][1:]] == ["timeout", "timeout"]
    assert evidence["private_baseline_verified"] is True


def test_private_requires_verified_https_and_real_tcp_reachability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    class Connected:
        def __enter__(self) -> Connected:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def connect(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Connected:
        return Connected()

    monkeypatch.setattr(probe.socket, "create_connection", connect)

    evidence = probe.run_plan(_private_plan(), ca_file=tmp_path / "ca.crt")

    assert evidence["outcome"] == "expectations_met"
    assert evidence["results"][0]["tls_verified"] is True
    assert all(item["tcp_connected"] for item in evidence["results"][1:])


def test_tls_error_cannot_satisfy_or_become_a_blocked_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    def failed_tls(*_args: object, **_kwargs: object) -> int:
        raise probe.ProbeError("verified HTTPS request failed: SSLCertVerificationError")

    def unexpected_connect(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        pytest.fail("TLS failure must stop before blocked endpoint checks")

    monkeypatch.setattr(probe, "_https_status", failed_tls)
    monkeypatch.setattr(probe.socket, "create_connection", unexpected_connect)

    with pytest.raises(probe.ProbeError, match="verified HTTPS request failed"):
        probe.run_plan(
            _public_plan(), ca_file=tmp_path / "ca.crt", private_baseline=_private_baseline()
        )


def test_tls_transport_error_is_not_accepted_as_tcp_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    def successful_status(
        _context: ssl.SSLContext,
        _origin: str,
        _path: str,
        _timeout: float,
        *,
        post_json: bool = False,
    ) -> int:
        del post_json
        return 200

    monkeypatch.setattr(probe, "_https_status", successful_status)

    def failed_connection(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        raise ssl.SSLError("wrong protocol")

    monkeypatch.setattr(probe.socket, "create_connection", failed_connection)

    with pytest.raises(probe.ProbeError, match="blocked TCP endpoint control was transport_error"):
        probe.run_plan(
            _public_plan(), ca_file=tmp_path / "ca.crt", private_baseline=_private_baseline()
        )


@pytest.mark.parametrize("error_number", [errno.ENETUNREACH, errno.EHOSTUNREACH])
def test_no_route_counts_as_blocked_only_after_exact_private_positive_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error_number: int
) -> None:
    _context(monkeypatch)

    def no_route(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        del timeout
        raise OSError(error_number, "route unavailable")

    monkeypatch.setattr(probe.socket, "create_connection", no_route)
    evidence = probe.run_plan(
        _public_plan(), ca_file=tmp_path / "ca.crt", private_baseline=_private_baseline()
    )
    assert all(item["observation"] == "no_route" for item in evidence["results"][1:])


def test_no_route_without_matching_private_baseline_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    def unexpected_connect(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        del timeout
        pytest.fail("network probe ran without matching private baseline")

    monkeypatch.setattr(probe.socket, "create_connection", unexpected_connect)
    baseline = _private_baseline()
    cast_results = baseline["results"]
    cast_results[1]["address"] = "10.20.0.99"

    with pytest.raises(
        probe.ProbeError,
        match="private baseline did not reach exact endpoint control",
    ):
        probe.run_plan(_public_plan(), ca_file=tmp_path / "ca.crt", private_baseline=baseline)


def test_admission_compares_each_replica_status_over_tls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)
    observed: list[str] = []

    def fake_status(
        _context: ssl.SSLContext,
        origin: str,
        path: str,
        timeout: float,
        *,
        post_json: bool = False,
    ) -> int:
        observed.append(origin)
        assert path == probe.ADMISSION_PATH
        assert post_json is True
        return 200 if len(observed) <= 3 else 429

    monkeypatch.setattr(probe, "_https_status", fake_status)
    plan = {
        "schema": probe.SCHEMA,
        "role": "admission",
        "timeout_seconds": 2,
        "targets": {"api": "https://api-lab", "replica": "https://api-replica-lab"},
        "requests": [
            {"target": "api", "expected_status": 200},
            {"target": "api", "expected_status": 200},
            {"target": "replica", "expected_status": 200},
            {"target": "api", "expected_status": 429},
        ],
    }

    evidence = probe.run_plan(plan, ca_file=tmp_path / "ca.crt")

    assert observed == [
        "https://api-lab",
        "https://api-lab",
        "https://api-replica-lab",
        "https://api-lab",
    ]
    assert [item["status"] for item in evidence["results"]] == [200, 200, 200, 429]
    assert all(item["tls_verified"] for item in evidence["results"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_origin", "http://api-lab"),
        ("api_origin", "https://user@api-lab"),
        ("blocked_endpoints", [{"id": "db", "address": "postgres", "port": 5432}]),
        ("blocked_endpoints", [{"id": "db", "address": "10.1.0.1", "port": True}]),
        ("role", []),
    ],
)
def test_public_plan_rejects_ambiguous_or_unbounded_targets(field: str, value: object) -> None:
    plan = _public_plan()
    plan[field] = value

    with pytest.raises(probe.ProbeError):
        probe.validate_plan(plan)


def test_positive_tcp_control_requires_actual_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _context(monkeypatch)

    def refused_connection(
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> Any:
        raise ConnectionRefusedError()

    monkeypatch.setattr(probe.socket, "create_connection", refused_connection)

    with pytest.raises(probe.ProbeError, match="reachable TCP endpoint postgres was refused"):
        probe.run_plan(_private_plan(), ca_file=tmp_path / "ca.crt")
