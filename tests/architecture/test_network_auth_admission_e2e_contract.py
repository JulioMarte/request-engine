from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/reference/compose.e2e.yaml"
REGISTRY = ROOT / "tests/system_e2e/suites.toml"
RUNNER_DOCKERFILE = ROOT / "deploy/reference/e2e-runner.Dockerfile"
API_PROXY = ROOT / "tests/system_e2e/fixtures/network-auth-api-proxy.conf"
CONTROL_PROXY = ROOT / "tests/system_e2e/fixtures/network-auth-control-proxy.conf"


def _service(source: str, name: str, next_name: str) -> str:
    marker = f"  {name}:\n"
    next_marker = f"\n  {next_name}:\n"
    assert marker in source, f"Compose is missing service {name}"
    return source.split(marker, 1)[1].split(next_marker, 1)[0]


def test_suite_uses_the_declared_network_boundary_driver_and_shared_limit() -> None:
    suites = cast(dict[str, dict[str, object]], tomllib.loads(REGISTRY.read_text())["suites"])
    spec = suites["network-auth-admission"]
    assert spec["driver"] == "network-boundary"
    assert spec["fresh_world"] is True
    assert set(cast(list[str], spec["services"])) == {"api", "api-replica", "control-plane"}
    assert set(cast(list[str], spec["ingress_services"])) == {"api-ingress", "control-ingress"}
    assert set(cast(list[str], spec["tls_hosts"])) == {
        "api-lab",
        "api-replica-lab",
        "control-lab",
    }
    assert "REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE=3" in cast(
        list[str], spec["environment"]
    )


def test_replicas_use_same_app_image_database_and_admission_limit() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    public_env = source.split("x-public-env:", 1)[1].split("x-platform-env:", 1)[0]
    platform_env = source.split("x-platform-env:", 1)[1].split("services:", 1)[0]
    api = _service(source, "api", "api-replica")
    replica = _service(source, "api-replica", "control-plane")
    assert "<<: *request-engine" in api and "<<: *request-engine" in replica
    assert "<<: *public-env" in api and "<<: *public-env" in replica
    assert "REQUEST_ENGINE_DATABASE_URL" in public_env
    assert "REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE" in public_env
    assert "REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE" in platform_env
    assert "profiles: [network-lab]" in replica
    assert "networks: [edge, backend]" in api
    assert "networks: [edge, backend]" in replica


def test_probes_have_separate_network_vantages_and_no_host_ports() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    api_ingress = _service(source, "api-ingress", "control-ingress")
    control_ingress = _service(source, "control-ingress", "public-probe")
    public_probe = _service(source, "public-probe", "private-probe")
    private_probe = _service(source, "private-probe", "smtp-provider")
    runner = _service(source, "e2e-runner", "networks")

    assert "public-ingress:" in api_ingress and "aliases: [api-lab, api-replica-lab]" in api_ingress
    assert "private-ingress:" in control_ingress and "aliases: [control-lab]" in control_ingress
    assert "ports:" not in api_ingress + control_ingress
    assert "networks: [public-ingress]" in public_probe
    assert "backend" not in public_probe and "edge" not in public_probe
    assert "networks: [private-ingress, backend]" in private_probe
    assert "public-ingress" not in private_probe and "edge" not in private_probe
    assert "networks: [edge]" in runner

    networks = source.rsplit("networks:\n", 1)[1]
    assert "public-ingress:\n    internal: true" in networks
    assert "private-ingress:\n    internal: true" in networks
    assert "backend:\n    internal: true" in networks


def test_ingress_tls_and_probe_image_are_confined_to_their_roles() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    api_ingress = _service(source, "api-ingress", "control-ingress")
    control_ingress = _service(source, "control-ingress", "public-probe")
    assert "api-lab.key:/tls/api-lab.key:ro" in api_ingress
    assert "api-replica-lab.key:/tls/api-replica-lab.key:ro" in api_ingress
    assert "control-lab.key:/tls/control-lab.key:ro" in control_ingress
    assert "ca.key" not in api_ingress + control_ingress

    dockerfile = RUNNER_DOCKERFILE.read_text(encoding="utf-8")
    assert (
        "COPY tests/system_e2e/network_boundary_probe.py /e2e/network_boundary_probe.py"
        in dockerfile
    )
    assert "psycopg" not in dockerfile.lower()
    assert "docker.sock" not in dockerfile.lower()

    api_proxy = API_PROXY.read_text(encoding="utf-8")
    control_proxy = CONTROL_PROXY.read_text(encoding="utf-8")
    assert "server_name api-lab;" in api_proxy
    assert "server_name api-replica-lab;" in api_proxy
    assert "server_name control-lab;" in control_proxy
    assert "proxy_pass http://request_engine_api;" in api_proxy
    assert "proxy_pass http://request_engine_api_replica;" in api_proxy
    assert "proxy_pass http://control-plane:8001;" in control_proxy
