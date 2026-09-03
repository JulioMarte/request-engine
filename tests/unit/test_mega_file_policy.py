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


def test_core_file_above_500_is_not_a_blocking_invariant() -> None:
    policy = _load_policy()
    assert (
        policy.mega_file_failure(
            Path("src/request_engine/modules/booking/application/mega.py"),
            category="production_application",
            current=501,
            previous=480,
            base_exceptions={},
        )
        is None
    )


def test_module_root_composition_file_is_measured_but_not_hard_blocked() -> None:
    policy = _load_policy()
    path = Path("src/request_engine/modules/booking/install.py")
    assert policy.is_core_mega_scope(path, "production_other") is True
    assert (
        policy.mega_file_failure(
            path,
            category="production_other",
            current=700,
            previous=480,
            base_exceptions={},
        )
        is None
    )


def test_non_core_file_above_500_is_not_blocked() -> None:
    policy = _load_policy()
    assert (
        policy.mega_file_failure(
            Path("scripts/ci/large_probe.py"),
            category="scripts",
            current=900,
            previous=400,
            base_exceptions={},
        )
        is None
    )


def test_product_and_quality_policy_change_is_not_a_hard_cooccurrence_failure() -> None:
    policy = _load_policy()
    product = Path("src/request_engine/modules/booking/application/mega.py")
    assert (
        policy.policy_self_modification_failure(
            changed_paths={product.as_posix(), "scripts/ci/mega_file_policy.py"},
            changed_core_python=[product],
        )
        is None
    )


def test_policy_authority_surface_excludes_unrelated_developer_experience_paths() -> None:
    policy = _load_policy()
    assert ".githooks/pre-push" not in policy.MEGA_POLICY_AUTHORITY_PATHS
    assert "scripts/dev/certify_push.py" not in policy.MEGA_POLICY_AUTHORITY_PATHS
    assert "scripts/dev/install_git_hooks.py" not in policy.MEGA_POLICY_AUTHORITY_PATHS
    assert "scripts/ci/mega_file_policy.py" in policy.MEGA_POLICY_AUTHORITY_PATHS


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


def test_same_change_exception_is_not_read_from_the_base(
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
    _git(tmp_path, "commit", "--quiet", "-m", "calibration exception")

    policy = _load_policy()
    base_exceptions = cast(
        dict[str, dict[str, object]],
        policy.load_base_exceptions("HEAD~1"),
    )
    assert base_exceptions == {}


def test_base_exception_registry_remains_parseable_calibration_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "src/request_engine/modules/booking/application/mega.py"
    monkeypatch.chdir(tmp_path)
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "quality-probe@example.invalid")
    _git(tmp_path, "config", "user.name", "Quality Probe")
    _write_registry(tmp_path, [_exception(path)])
    _git(tmp_path, "add", "docs/engineering-quality/mega-file-exceptions.v1.json")
    _git(tmp_path, "commit", "--quiet", "-m", "calibration exception base")
    (tmp_path / "README.md").write_text("implementation\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "--quiet", "-m", "implementation")

    policy = _load_policy()
    raw: Any = policy.load_base_exceptions("HEAD~1")
    base_exceptions = cast(dict[str, dict[str, object]], raw)
    assert base_exceptions[path]["max_effective_loc"] == 650
