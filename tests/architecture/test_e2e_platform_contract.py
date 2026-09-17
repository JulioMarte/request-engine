from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITES_PATH = ROOT / "tests" / "system_e2e" / "suites.toml"
COMPOSE_PATH = ROOT / "deploy" / "reference" / "compose.e2e.yaml"
RUNNER_PATH = ROOT / "tests" / "system_e2e" / "runner.py"


def _suite_catalog() -> dict[str, dict[str, object]]:
    catalog = tomllib.loads(SUITES_PATH.read_text(encoding="utf-8"))
    suites = catalog.get("suites")
    assert isinstance(suites, dict)
    return cast(dict[str, dict[str, object]], suites)


def _enabled_suites() -> dict[str, dict[str, object]]:
    return {
        name: spec
        for name, spec in _suite_catalog().items()
        if spec.get("enabled") is True
    }


def _compose_services() -> dict[str, dict[str, object]]:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose.get("services")
    assert isinstance(services, dict)
    return cast(dict[str, dict[str, object]], services)


def _string_list(spec: dict[str, object], field: str, suite: str) -> list[str]:
    value = spec[field]
    assert isinstance(value, list), f"{suite}.{field} must be a list"
    result: list[str] = []
    for item in value:
        assert isinstance(item, str), f"{suite}.{field} must contain only strings"
        result.append(item)
    return result


def test_e2e_runner_remains_black_box() -> None:
    runner = RUNNER_PATH.read_text(encoding="utf-8")
    assert "import request_engine" not in runner
    assert "from request_engine" not in runner
    assert "psycopg" not in runner
    assert "sqlalchemy" not in runner
    assert "/var/run/docker.sock" not in runner


def test_postgres_is_not_exposed_to_e2e_runner_network() -> None:
    services = _compose_services()
    runner_networks = set(services["e2e-runner"]["networks"])
    postgres_networks = set(services["postgres"]["networks"])
    assert runner_networks.isdisjoint(postgres_networks)


def test_worker_has_no_placeholder_principal_or_empty_publisher() -> None:
    worker = _compose_services()["worker"]
    environment = worker["environment"]
    assert isinstance(environment, dict)
    principal = environment["REQUEST_ENGINE_WORKER_PRINCIPAL_ID"]
    publisher = environment["REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY"]
    assert principal != "00000000-0000-0000-0000-000000000000"
    assert publisher


def test_worker_identity_is_runtime_handoff_not_static_compose_state() -> None:
    worker = _compose_services()["worker"]
    environment = worker["environment"]
    assert isinstance(environment, dict)
    assert environment["REQUEST_ENGINE_WORKER_PRINCIPAL_ID"] == "${REQUEST_ENGINE_WORKER_PRINCIPAL_ID:?worker principal required}"


def test_enabled_e2e_suites_have_unique_selectors_and_namespaces() -> None:
    selectors: set[str] = set()
    namespaces: set[str] = set()
    for name, spec in _enabled_suites().items():
        selector = spec.get("selector")
        namespace = spec.get("artifact_namespace")
        assert isinstance(selector, str) and selector
        assert isinstance(namespace, str) and namespace
        assert selector not in selectors, f"duplicate suite selector: {selector}"
        assert namespace not in namespaces, f"duplicate artifact namespace: {namespace}"
        selectors.add(selector)
        namespaces.add(namespace)
        assert spec.get("fresh_world") is True, f"{name} must run from a fresh world"


def test_enabled_e2e_suite_dependencies_and_faults_are_supported() -> None:
    allowed_services = {"api", "control-plane", "worker"}
    allowed_profiles = {"worker", "secrets", "delivery", "oidc"}
    allowed_fault_actions = {"kill-restart"}
    mapping_pattern = re.compile(r"^[A-Z][A-Z0-9_]*=[^/:]+\.json:[A-Za-z0-9_.-]+$")
    for name, spec in _enabled_suites().items():
        services = set(_string_list(spec, "services", name))
        profiles = set(_string_list(spec, "profiles", name))
        deferred = set(_string_list(spec, "deferred_services", name))
        mappings = _string_list(spec, "runtime_env_from_state", name)
        faults = _string_list(spec, "faults", name)
        assert services, f"{name} must declare at least one runtime service"
        assert services <= allowed_services, f"{name} declares unsupported services: {services}"
        assert profiles <= allowed_profiles, f"{name} declares unsupported profiles: {profiles}"
        assert deferred <= services, f"{name} defers services it does not declare: {deferred}"
        assert bool(deferred) is bool(mappings), (
            f"{name} deferred services and runtime state mappings must be paired"
        )
        for mapping in mappings:
            message = f"{name} has invalid state mapping: {mapping}"
            assert mapping_pattern.fullmatch(mapping), message
        if "worker" in services:
            assert "worker" in profiles, f"{name} must enable the worker profile"
            assert "worker" in deferred, (
                f"{name} must provision worker identity before start"
            )
        assert bool(faults) is bool(spec["fault_injection"]), (
            f"{name} fault_injection must match whether faults are declared"
        )
        for fault in faults:
            target, separator, action = fault.partition(":")
            assert separator and target in services, f"{name} has invalid fault target: {fault}"
            assert action in allowed_fault_actions, f"{name} has unsupported fault action: {fault}"
