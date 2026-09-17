from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "tests/system_e2e/suites.toml"
RUNNER_DOCKERFILE = ROOT / "deploy/reference/e2e-runner.Dockerfile"
RUNNER = ROOT / "tests/system_e2e/runner.py"


def test_enabled_e2e_suites_have_reusable_registry_contract() -> None:
    suites = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))["suites"]
    required = {
        "description",
        "selector",
        "profiles",
        "services",
        "fresh_world",
        "fault_injection",
        "cost",
        "artifact_namespace",
        "pr",
        "merge",
        "nightly",
        "manual",
        "enabled",
    }
    enabled = {name: spec for name, spec in suites.items() if spec.get("enabled", True)}
    assert len(enabled) >= 2, "the reusable platform must exercise more than one suite"
    namespaces: set[str] = set()
    selectors: set[str] = set()
    for name, spec in enabled.items():
        missing = required - set(spec)
        assert not missing, f"{name} is missing registry fields: {sorted(missing)}"
        assert spec["fresh_world"] is True, (
            f"{name} must default to an isolated authoritative world"
        )
        namespace = spec["artifact_namespace"]
        selector = spec["selector"]
        assert namespace not in namespaces, f"duplicate E2E artifact namespace: {namespace}"
        assert selector not in selectors, f"duplicate E2E selector: {selector}"
        namespaces.add(namespace)
        selectors.add(selector)


def test_enabled_e2e_suite_dependencies_are_supported() -> None:
    suites = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))["suites"]
    allowed_services = {"api", "control-plane", "worker"}
    allowed_profiles = {"worker", "secrets", "delivery", "oidc"}
    for name, spec in suites.items():
        if not spec.get("enabled", True):
            continue
        services = set(spec["services"])
        profiles = set(spec["profiles"])
        assert services, f"{name} must declare at least one runtime service"
        assert services <= allowed_services, f"{name} declares unsupported services: {services}"
        assert profiles <= allowed_profiles, f"{name} declares unsupported profiles: {profiles}"
        if "worker" in services:
            assert "worker" in profiles, f"{name} must enable the worker profile"


def test_black_box_runner_image_cannot_install_application_shortcuts() -> None:
    dockerfile = RUNNER_DOCKERFILE.read_text(encoding="utf-8").lower()
    forbidden = (
        "src/request_engine",
        "pip install",
        "uv sync",
        "psycopg",
        "sqlalchemy",
        "docker.sock",
    )
    found = [token for token in forbidden if token in dockerfile]
    assert not found, (
        f"black-box runner Dockerfile contains forbidden application/database shortcuts: {found}"
    )


def test_black_box_runner_does_not_import_request_engine() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "import request_engine" not in source
    assert "from request_engine" not in source
