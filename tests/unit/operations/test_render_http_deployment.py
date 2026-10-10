from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "render_http_deployment",
    Path(__file__).resolve().parents[3] / "scripts/operations/render_http_deployment.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts/operations/render_http_deployment.py"


def _plan() -> dict[str, Any]:
    return {
        "schema": "request-engine/http-deployment-plan/v1",
        "image": "registry.example/request-engine@sha256:" + "a" * 64,
        "api_env_file": "/etc/request-engine/api.env",
        "control_env_file": "/etc/request-engine/control.env",
        "public_api": {
            "host_ip": "127.0.0.1",
            "published_port": 18000,
            "trusted_proxy_source": "127.0.0.1",
        },
        "private_control": {
            "host_ip": "10.20.30.40",
            "published_port": 18001,
            "trusted_proxy_source": "10.20.30.41",
        },
        "webauthn": {
            "rp_id": "example.com",
            "allowed_origins": ["https://console.example.com", "https://api.example.com"],
        },
        "firewall_configuration_reference": "host-fw-change-421",
    }


def _set_plan_value(plan: dict[str, Any], field: str, value: Any) -> None:
    parts = field.split(".")
    target = plan
    for part in parts[:-1]:
        target = cast(dict[str, Any], target[part])
    target[parts[-1]] = value


@pytest.mark.unit
def test_renders_valid_compose_with_split_planes_and_no_inline_secrets() -> None:
    rendered = module.render_compose(_plan())
    compose = yaml.safe_load(rendered)

    assert set(compose["services"]) == {"api", "control-plane"}
    api = compose["services"]["api"]
    control = compose["services"]["control-plane"]
    assert api["image"] == control["image"] == _plan()["image"]
    assert api["user"] == control["user"] == "10001:10001"
    assert api["networks"] == ["public_edge"]
    assert control["networks"] == ["private_control"]
    assert api["ports"] == [
        {"target": 8000, "published": "18000", "host_ip": "127.0.0.1", "protocol": "tcp"}
    ]
    assert control["ports"] == [
        {"target": 8001, "published": "18001", "host_ip": "10.20.30.40", "protocol": "tcp"}
    ]
    assert api["env_file"] == ["/etc/request-engine/api.env"]
    assert control["env_file"] == ["/etc/request-engine/control.env"]
    assert api["command"][1] == "request_engine.bootstrap.server:create_app"
    assert control["command"][1] == "request_engine.bootstrap.platform_server:create_app"
    assert "--forwarded-allow-ips=127.0.0.1/32" in api["command"]
    assert "REQUEST_ENGINE_WEBAUTHN_RP_ID" in api["environment"]
    assert "REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS" in control["environment"]
    assert "postgres" not in compose["services"]
    assert "openbao" not in compose["services"]
    assert "password" not in rendered.lower()
    assert compose["x-request-engine-acceptance"]["host_isolation_certified"] is False
    assert (
        compose["x-request-engine-acceptance"]["firewall_configuration_reference"]
        == "host-fw-change-421"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("public_api.host_ip", "192.168.2.4", "loopback-only"),
        ("public_api.host_ip", "::", "wildcard"),
        ("private_control.host_ip", "0.0.0.0", "wildcard"),
        ("private_control.host_ip", "2001:4860:4860::8888", "RFC1918"),
        ("private_control.host_ip", "224.0.0.1", "wildcard or multicast"),
        ("image", "registry.example/re:latest", "sha256 digest"),
        ("public_api.trusted_proxy_source", "0.0.0.0/0", "trust all"),
        ("private_control.trusted_proxy_source", "::/0", "trust all"),
        ("public_api.trusted_proxy_source", "192.0.2.0/24", "one host"),
        ("public_api.trusted_proxy_source", "2001:db8:1::/64", "one host"),
        ("private_control.trusted_proxy_source", "198.51.100.0/24", "one host"),
        ("private_control.trusted_proxy_source", "2001:db8:2::/64", "one host"),
        ("api_env_file", "/etc/$secret.env", "absolute normalized"),
        ("control_env_file", "/etc/%ENV%.env", "absolute normalized"),
        ("api_env_file", "/etc/a:b.env", "absolute normalized"),
        ("api_env_file", "/etc/a\n.env", "absolute normalized"),
        ("control_env_file", "/etc/request-engine/api.env", "separate environment"),
        (
            "webauthn.allowed_origins",
            ["http://console.example.com"],
            "HTTPS",
        ),
        (
            "webauthn.allowed_origins",
            ["\nhttps://console.example.com"],
            "HTTPS",
        ),
        (
            "webauthn.allowed_origins",
            ["https://console.example.com", "https://console.example.com/"],
            "unique HTTPS",
        ),
    ],
)
def test_rejects_malicious_or_incomplete_plan(field: str, value: Any, message: str) -> None:
    plan = _plan()
    _set_plan_value(plan, field, value)
    with pytest.raises(module.DeploymentPlanError, match=message):
        module.validate_plan(plan)


@pytest.mark.unit
def test_cli_rejects_oversized_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan()) + " " * (64 * 1024), encoding="utf-8")
    result = subprocess.run(
        ["python", str(SCRIPT_PATH), str(plan_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "exceeds 64 KiB" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("public_api.trusted_proxy_source", "192.0.2.7/32", "192.0.2.7/32"),
        ("public_api.trusted_proxy_source", "2001:db8::7/128", "2001:db8::7/128"),
        ("private_control.trusted_proxy_source", "198.51.100.8/32", "198.51.100.8/32"),
        ("private_control.trusted_proxy_source", "2001:db8::8/128", "2001:db8::8/128"),
    ],
)
def test_accepts_only_explicit_single_host_proxy_prefixes(
    field: str, value: str, expected: str
) -> None:
    plan = _plan()
    _set_plan_value(plan, field, value)

    rendered = yaml.safe_load(module.render_compose(plan))
    command = rendered["services"]["api" if field.startswith("public_api") else "control-plane"][
        "command"
    ]
    assert f"--forwarded-allow-ips={expected}" in command


@pytest.mark.unit
def test_docker_compose_config_when_available(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is unavailable; generated YAML is parsed structurally above")
    plan_path = tmp_path / "plan.json"
    compose_path = tmp_path / "compose.yaml"
    plan = _plan()
    for field in ("api_env_file", "control_env_file"):
        env_path = tmp_path / f"{field}.env"
        env_path.write_text("", encoding="utf-8")
        plan[field] = str(env_path)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    subprocess.run(
        ["python", str(SCRIPT_PATH), str(plan_path), "--output", str(compose_path)],
        check=True,
    )
    subprocess.run(
        [docker, "compose", "-f", str(compose_path), "config", "--quiet"],
        check=True,
        capture_output=True,
        text=True,
    )
