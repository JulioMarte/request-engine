from __future__ import annotations

import ast
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "tests/system_e2e/suites.toml"
RUNNER_DOCKERFILE = ROOT / "deploy/reference/e2e-runner.Dockerfile"
RUNNER = ROOT / "tests/system_e2e/runner.py"
COMPOSE = ROOT / "deploy/reference/compose.e2e.yaml"
DOCKER_RETRY = ROOT / "scripts/ci/retry_transient_docker.sh"


def _enabled_suites() -> dict[str, dict[str, object]]:
    suites = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))["suites"]
    return {name: spec for name, spec in suites.items() if spec.get("enabled", True)}


def _string_list(spec: dict[str, object], key: str, suite: str) -> list[str]:
    value = spec[key]
    assert isinstance(value, list), f"{suite}.{key} must be a list"
    raw_items = cast(list[object], value)
    items: list[str] = []
    for item in raw_items:
        assert isinstance(item, str), f"{suite}.{key} must contain only strings"
        items.append(item)
    return items


def _runner_selectors() -> set[str]:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "SUITES":
            continue
        assert isinstance(node.value, ast.Dict), "runner SUITES must remain a static dict literal"
        selectors: set[str] = set()
        for key in node.value.keys:
            assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
                "runner SUITES keys must remain static string literals"
            )
            selectors.add(key.value)
        return selectors
    raise AssertionError("generic E2E runner does not declare a static SUITES registry")


def test_enabled_e2e_suites_have_reusable_registry_contract() -> None:
    enabled = _enabled_suites()
    required = {
        "description",
        "selector",
        "profiles",
        "services",
        "deferred_services",
        "runtime_env_from_state",
        "faults",
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
    assert len(enabled) >= 2, "the reusable platform must exercise more than one suite"
    namespaces: set[object] = set()
    selectors: set[object] = set()
    for name, spec in enabled.items():
        missing = required - set(spec)
        assert not missing, f"{name} is missing registry fields: {sorted(missing)}"
        assert spec["fresh_world"] is True, (
            f"{name} must default to an isolated authoritative world"
        )
        namespace = spec["artifact_namespace"]
        selector = spec["selector"]
        assert isinstance(namespace, str), f"{name}.artifact_namespace must be a string"
        assert isinstance(selector, str), f"{name}.selector must be a string"
        assert namespace not in namespaces, f"duplicate E2E artifact namespace: {namespace}"
        assert selector not in selectors, f"duplicate E2E selector: {selector}"
        namespaces.add(namespace)
        selectors.add(selector)


def test_enabled_registry_selectors_are_executable_by_generic_runner() -> None:
    enabled = _enabled_suites()
    registered = {str(spec["selector"]) for spec in enabled.values()}
    implemented = _runner_selectors()
    assert registered <= implemented, (
        f"registered E2E selectors missing from generic runner: {sorted(registered - implemented)}"
    )


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
            assert "worker" in deferred, f"{name} must provision worker identity before start"
        assert bool(faults) is bool(spec["fault_injection"]), (
            f"{name} fault_injection must match whether faults are declared"
        )
        for fault in faults:
            target, separator, action = fault.partition(":")
            assert separator and target in services, f"{name} has invalid fault target: {fault}"
            assert action in allowed_fault_actions, f"{name} has unsupported fault action: {fault}"


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


def test_reference_compose_keeps_database_credentials_need_to_know() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    assert "x-common-env:" not in source
    public_env = source.split("x-public-env:", 1)[1].split("x-platform-env:", 1)[0]
    platform_env = source.split("x-platform-env:", 1)[1].split("services:", 1)[0]
    worker = source.split("\n  worker:\n", 1)[1].split("\n  e2e-runner:\n", 1)[0]
    assert "WORKER_DATABASE_URL" not in public_env
    assert "PLATFORM_READ_DATABASE_URL" not in public_env
    assert "APPOINTMENT_OPTION_SIGNING_KEY" not in platform_env
    assert "WORKER_DATABASE_URL" not in platform_env
    assert "PLATFORM_READ_DATABASE_URL" not in worker
    assert "PLATFORM_CONTROL_DATABASE_URL" not in worker
    assert "APPOINTMENT_OPTION_SIGNING_KEY" not in worker
    assert "REQUEST_ENGINE_WORKER_PRINCIPAL_ID:-00000000" not in worker
    assert "http_outbox_publisher:create_publisher" in worker
    assert "REQUEST_ENGINE_OUTBOX_PUBLISH_URL" in worker


def test_docker_retry_is_bounded_and_transient_only() -> None:
    source = DOCKER_RETRY.read_text(encoding="utf-8")
    assert "E2E_DOCKER_RETRY_ATTEMPTS:-3" in source
    assert "E2E_DOCKER_RETRY_DELAY_SECONDS:-3" in source
    assert "reason=non-transient" in source
    assert "docker-retry=exhausted" in source
    assert "TLS handshake timeout" in source
    assert "failed to fetch anonymous token" in source
    assert "toomanyrequests" in source


def test_docker_retry_retries_transient_failure_then_succeeds(tmp_path: Path) -> None:
    log = tmp_path / "retry.log"
    counter = tmp_path / "counter"
    command = (
        'count=0; [[ -f "$1" ]] && count=$(cat "$1"); count=$((count + 1)); '
        'echo "$count" > "$1"; if ((count < 2)); then '
        'echo "TLS handshake timeout" >&2; exit 1; fi'
    )
    result = subprocess.run(
        ["bash", str(DOCKER_RETRY), str(log), "bash", "-c", command, "bash", str(counter)],
        check=False,
        env={
            **os.environ,
            "E2E_DOCKER_RETRY_ATTEMPTS": "3",
            "E2E_DOCKER_RETRY_DELAY_SECONDS": "0",
        },
    )
    assert result.returncode == 0
    assert counter.read_text(encoding="utf-8").strip() == "2"
    assert "docker-retry=scheduled" in log.read_text(encoding="utf-8")


def test_docker_retry_does_not_repeat_deterministic_failure(tmp_path: Path) -> None:
    log = tmp_path / "retry.log"
    counter = tmp_path / "counter"
    command = (
        'count=0; [[ -f "$1" ]] && count=$(cat "$1"); count=$((count + 1)); '
        'echo "$count" > "$1"; echo "Dockerfile syntax error" >&2; exit 17'
    )
    result = subprocess.run(
        ["bash", str(DOCKER_RETRY), str(log), "bash", "-c", command, "bash", str(counter)],
        check=False,
        env={
            **os.environ,
            "E2E_DOCKER_RETRY_ATTEMPTS": "3",
            "E2E_DOCKER_RETRY_DELAY_SECONDS": "0",
        },
    )
    assert result.returncode == 17
    assert counter.read_text(encoding="utf-8").strip() == "1"
    assert "reason=non-transient" in log.read_text(encoding="utf-8")
