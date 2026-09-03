from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
POLICY_TEST = ROOT / "tests" / "architecture" / "test_dependency_policy.py"
SRC_ROOT = ROOT / "src"


def _load_policy_test() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "dependency_policy_guardrail_under_test",
        POLICY_TEST,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conformance_public_contract_import_is_recognized_as_contract_surface() -> None:
    policy = _load_policy_test()
    target = policy._cross_module_target(
        "booking",
        "request_engine.modules.queue.contracts.QueueRead",
    )
    assert target == ("queue", "contracts")


def test_conformance_absolute_internal_import_cannot_masquerade_as_public_surface() -> None:
    policy = _load_policy_test()
    for surface in ("domain", "application", "adapters", "api"):
        target = policy._cross_module_target(
            "booking",
            f"request_engine.modules.queue.{surface}.HiddenThing",
        )
        assert target == ("queue", surface)
        assert target[1] != "contracts"


def test_conformance_relative_internal_import_resolves_to_same_forbidden_surface() -> None:
    policy = _load_policy_test()
    path = SRC_ROOT / "request_engine/modules/booking/application/probe.py"
    tree = ast.parse("from ...queue.domain import QueueEntry\n")
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom)
    resolved = policy._resolved_import_from(path, node)
    assert resolved == "request_engine.modules.queue.domain"
    assert policy._cross_module_target("booking", f"{resolved}.QueueEntry") == (
        "queue",
        "domain",
    )


def test_conformance_relative_contract_import_is_not_false_positive() -> None:
    policy = _load_policy_test()
    path = SRC_ROOT / "request_engine/modules/booking/application/probe.py"
    tree = ast.parse("from ...queue.contracts import QueueRead\n")
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom)
    resolved = policy._resolved_import_from(path, node)
    assert resolved == "request_engine.modules.queue.contracts"
    assert policy._cross_module_target("booking", f"{resolved}.QueueRead") == (
        "queue",
        "contracts",
    )


def test_conformance_same_module_import_is_not_cross_module_dependency() -> None:
    policy = _load_policy_test()
    assert (
        policy._cross_module_target(
            "booking",
            "request_engine.modules.booking.domain.Reservation",
        )
        is None
    )


def test_conformance_cycle_detector_catches_direct_and_transitive_cycles() -> None:
    policy = _load_policy_test()
    find_cycle = cast(object, policy._find_cycle)
    assert callable(find_cycle)
    assert find_cycle({"a": {"b"}, "b": {"a"}}) is not None
    assert find_cycle({"a": {"b"}, "b": {"c"}, "c": {"a"}}) is not None
    assert find_cycle({"a": {"b"}, "b": {"c"}, "c": set()}) is None


def test_conformance_static_checker_does_not_claim_runtime_dependency_coverage() -> None:
    """Record the current false-negative boundary instead of pretending it is solved.

    ``importlib.import_module`` and service-locator indirection are not static
    import statements. They remain prohibited as metric/policy gaming by
    governance, but this AST import guardrail does not claim to prove their
    absence. If runtime dependency instrumentation is added later, this fixture
    should evolve with the declared protected property rather than silently
    widening what the current static checker claims to know.
    """
    tree = ast.parse(
        "import importlib\n"
        "target = importlib.import_module('request_engine.modules.queue.domain')\n"
    )
    static_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert static_nodes == []
