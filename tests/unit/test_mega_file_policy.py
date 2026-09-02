from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts" / "ci" / "mega_file_policy.py"


def _load_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mega_file_policy_under_test", POLICY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exception(path: str, ceiling: int = 650) -> dict[str, object]:
    return {
        "path": path,
        "max_effective_loc": ceiling,
        "rationale": (
            "This cohesive core mapping is intentionally kept local because decomposition "
            "would add navigation without creating an independent responsibility."
        ),
        "approval_ref": "architecture-exception-pr-123",
    }


def test_core_file_above_500_is_blocking_without_base_exception() -> None:
    policy = _load_policy()
    failure = policy.mega_file_failure(
        Path("src/request_engine/modules/booking/application/mega.py"),
        category="production_application",
        current=501,
        previous=480,
        base_exceptions={},
    )
    assert failure is not None
    assert failure["classification"] == "INVARIANT_FAILURE"
    assert failure["trigger_id"] == "QR-MEGA-001"
    assert failure["exception_source"] == "base-ref-only"


def test_module_root_composition_file_cannot_evade_scope_as_production_other() -> None:
    policy = _load_policy()
    failure = policy.mega_file_failure(
        Path("src/request_engine/modules/booking/install.py"),
        category="production_other",
        current=501,
        previous=480,
        base_exceptions={},
    )
    assert failure is not None
    assert failure["trigger_id"] == "QR-MEGA-001"


def test_non_core_file_above_500_remains_semantic_review_territory() -> None:
    policy = _load_policy()
    failure = policy.mega_file_failure(
        Path("scripts/ci/large_probe.py"),
        category="scripts",
        current=900,
        previous=400,
        base_exceptions={},
    )
    assert failure is None


def test_legacy_core_mega_file_may_shrink_without_new_exception() -> None:
    policy = _load_policy()
    failure = policy.mega_file_failure(
        Path("src/request_engine/modules/booking/domain/legacy.py"),
        category="production_domain",
        current=590,
        previous=620,
        base_exceptions={},
    )
    assert failure is None


def test_base_exception_has_a_bounded_effective_loc_ceiling() -> None:
    policy = _load_policy()
    path = "src/request_engine/modules/booking/application/mega.py"
    base_exceptions = {path: _exception(path, ceiling=650)}
    allowed = policy.mega_file_failure(
        Path(path),
        category="production_application",
        current=640,
        previous=480,
        base_exceptions=base_exceptions,
    )
    blocked = policy.mega_file_failure(
        Path(path),
        category="production_application",
        current=651,
        previous=480,
        base_exceptions=base_exceptions,
    )
    assert allowed is None
    assert blocked is not None
    assert "ceiling of 650" in str(blocked["reason"])


def test_product_change_cannot_modify_the_policy_that_judges_it() -> None:
    policy = _load_policy()
    product = Path("src/request_engine/modules/booking/application/mega.py")
    failure = policy.policy_self_modification_failure(
        changed_paths={
            product.as_posix(),
            "scripts/ci/mega_file_policy.py",
        },
        changed_core_python=[product],
    )
    assert failure is not None
    assert failure["classification"] == "INVARIANT_FAILURE"
    assert failure["trigger_id"] == "QR-MEGA-GOV-001"
    assert failure["exception_source"] == "separate-governance-change-required"


def test_governance_only_change_may_evolve_policy_without_product_code() -> None:
    policy = _load_policy()
    failure = policy.policy_self_modification_failure(
        changed_paths={"scripts/ci/mega_file_policy.py"},
        changed_core_python=[],
    )
    assert failure is None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _write_registry(root: Path, entries: list[dict[str, object]]) -> None:
    target = root / "docs" / "engineering-quality" / "mega-file-exceptions.v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "mega-file-exceptions/v1",
        "policy": "test registry",
        "exceptions": entries,
    }
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_exception_added_in_same_change_is_not_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "src/request_engine/modules/booking/application/mega.py"
    monkeypatch.chdir(tmp_path)
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "quality-probe@example.invalid")
    _git(tmp_path, "config", "user.name", "Quality Probe")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "--quiet", "-m", "base")

    _write_registry(tmp_path, [_exception(path)])
    _git(tmp_path, "add", "docs/engineering-quality/mega-file-exceptions.v1.json")
    _git(tmp_path, "commit", "--quiet", "-m", "self-approved exception")

    policy = _load_policy()
    base_exceptions = cast(
        dict[str, dict[str, object]],
        policy.load_base_exceptions("HEAD~1"),
    )
    assert base_exceptions == {}


def test_exception_merged_into_base_is_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "src/request_engine/modules/booking/application/mega.py"
    monkeypatch.chdir(tmp_path)
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "quality-probe@example.invalid")
    _git(tmp_path, "config", "user.name", "Quality Probe")
    _write_registry(tmp_path, [_exception(path)])
    _git(tmp_path, "add", "docs/engineering-quality/mega-file-exceptions.v1.json")
    _git(tmp_path, "commit", "--quiet", "-m", "approved exception base")
    (tmp_path / "README.md").write_text("implementation\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "--quiet", "-m", "implementation")

    policy = _load_policy()
    raw: Any = policy.load_base_exceptions("HEAD~1")
    base_exceptions = cast(dict[str, dict[str, object]], raw)
    assert base_exceptions[path]["max_effective_loc"] == 650
