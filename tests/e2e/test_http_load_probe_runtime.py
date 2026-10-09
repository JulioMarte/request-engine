"""Lab load evidence over real TCP, runtime credentials and PostgreSQL.

This detects dropped options writes and misleading probe success, rather than
certifying deployment capacity or production latency budgets.
"""

import asyncio
import importlib.util
import json
import socket
from pathlib import Path
from uuid import uuid4

import pytest
from uvicorn import Config, Server

from request_engine.bootstrap.server import create_app

from .conftest import PgConnection, RuntimeCredentials

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.capacity,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

spec = importlib.util.spec_from_file_location(
    "runtime_load_probe",
    Path(__file__).resolve().parents[2] / "scripts/operations/http_load_probe.py",
)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.asyncio
async def test_bounded_probe_exercises_real_runtime_and_persists_every_option(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"load-proof-{authority_id}"),
    )
    for name, value in {
        "REQUEST_ENGINE_DATABASE_URL": app_runtime_credentials.database_url,
        "REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID": str(authority_id),
        "REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY": "a" * 64,
        "REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY": "b" * 64,
        "REQUEST_ENGINE_OIDC_ENABLED": "false",
        "REQUEST_ENGINE_WEBAUTHN_RP_ID": "localhost",
        "REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS": "http://localhost",
        "REQUEST_ENGINE_WEBAUTHN_DECOY_KEY": "d" * 64,
        "REQUEST_ENGINE_DB_POOL_SIZE": "1",
        "REQUEST_ENGINE_DB_POOL_MAX_OVERFLOW": "1",
        "REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE": "120",
    }.items():
        monkeypatch.setenv(name, value)
    server = Server(Config(create_app(), log_level="error", access_log=False))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if serving.done():
                        await serving
                        pytest.fail("Runtime stopped before startup")
                    await asyncio.sleep(0.01)
            for path, method, total, concurrency in [
                ("/health/ready", "GET", 200, 2),
                ("/auth/native/webauthn/authentication-options", "POST", 100, 2),
            ]:
                evidence = await probe.run_plan(
                    {
                        "schema": "request-engine/http-load-plan/v1",
                        "mode": "lab",
                        "target_origin": origin,
                        "allowed_target_origins": [origin],
                        "allowed_paths": [path],
                        "request": {
                            "method": method,
                            "path": path,
                            "json_body": {} if method == "POST" else None,
                        },
                        "total_requests": total,
                        "concurrency": concurrency,
                        "timeout_seconds": 5,
                        "max_p95_ms": 5000,
                        "max_error_rate": 0,
                    }
                )
                print(json.dumps(evidence, sort_keys=True))
                assert evidence["production_certified"] is False
                assert evidence["outcome"] == "within_declared_budgets"
                assert evidence["status_counts"] == {"200": total}
                assert evidence["error_count"] == 0
            # The first 100 options consumed admission slots. The remaining 20
            # must persist; the following 30 must stop before authoritative SQL.
            rate_path = "/auth/native/webauthn/authentication-options"
            rejected = await probe.run_plan(
                {
                    "schema": "request-engine/http-load-plan/v1",
                    "mode": "lab",
                    "target_origin": origin,
                    "allowed_target_origins": [origin],
                    "allowed_paths": [rate_path],
                    "request": {"method": "POST", "path": rate_path, "json_body": {}},
                    "total_requests": 50,
                    "concurrency": 2,
                    "timeout_seconds": 5,
                    "max_p95_ms": 5000,
                    "max_error_rate": 0,
                }
            )
            print(json.dumps(rejected, sort_keys=True))
            assert rejected["outcome"] == "budget_exceeded"
            assert rejected["status_counts"] == {"200": 20, "429": 30}
            assert rejected["error_count"] == 30
            assert e2e_admin_conn.execute(
                "SELECT count(*) FROM request_engine.webauthn_challenges "
                "WHERE purpose = 'authentication_discoverable' AND status = 'pending'"
            ).fetchone() == (120,)
            assert e2e_admin_conn.execute(
                "SELECT count(*) FROM request_engine.native_sessions"
            ).fetchone() == (0,)
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=15)
