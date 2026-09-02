from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "check_python_file_budget.py"


def _load_budget_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_python_file_budget", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_effective_code_lines_ignore_blank_and_comment_only_lines() -> None:
    budget = _load_budget_module()
    source = """
# comment
value = 1  # inline comment

# another comment
other = 2
"""

    assert budget.effective_code_lines(source) == 2


def test_docstring_lines_count_as_python_content() -> None:
    budget = _load_budget_module()
    source = '''"""first
second
"""
value = 1
'''

    assert budget.effective_code_lines(source) == 4


def _candidate_function(
    budget: ModuleType,
) -> Callable[[Path, int, int | None], dict[str, object] | None]:
    return cast(
        Callable[[Path, int, int | None], dict[str, object] | None],
        budget._file_loc_candidate,
    )


def test_file_loc_threshold_creates_non_blocking_candidate_not_violation() -> None:
    budget = _load_budget_module()
    candidate_fn = _candidate_function(budget)
    path = Path("src/request_engine/example.py")

    assert candidate_fn(path, 120, None) is None
    candidate = candidate_fn(path, 121, None)
    assert candidate is not None
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert candidate["trigger_id"] == "QR-FSIZE-001"


def test_previously_oversized_file_is_still_review_evidence_not_a_ratchet_failure() -> None:
    budget = _load_budget_module()
    candidate_fn = _candidate_function(budget)
    path = Path("tests/example.py")

    shrunk = candidate_fn(path, 130, 140)
    grown = candidate_fn(path, 141, 140)
    assert shrunk is not None
    assert grown is not None
    assert shrunk["classification"] == "REVIEW_CANDIDATE"
    assert grown["classification"] == "REVIEW_CANDIDATE"
    shrunk_deltas = cast(list[dict[str, object]], shrunk["deltas"])
    grown_deltas = cast(list[dict[str, object]], grown["deltas"])
    assert shrunk_deltas[0]["delta"] == -10
    assert grown_deltas[0]["delta"] == 1


def test_changed_python_files_cover_categories_and_ignore_only_controlled_generated_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    for directory in ("tests", "scripts", "migrations"):
        (tmp_path / directory).mkdir()
    monkeypatch.chdir(tmp_path)
    git("init", "--quiet")
    git("config", "user.email", "quality-probe@example.invalid")
    git("config", "user.name", "Quality Probe")
    (tmp_path / "tests" / "base.py").write_text("value = 1\n", encoding="utf-8")
    git("add", "tests/base.py")
    git("commit", "--quiet", "-m", "base")
    (tmp_path / "scripts" / "probe.py").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "migrations" / "probe.py").write_text("value = 3\n", encoding="utf-8")
    (tmp_path / "tests" / "probe_generated.py").write_text("value = 4\n", encoding="utf-8")
    (tmp_path / "tests" / "fake_generated_header.py").write_text(
        "# @generated - DO NOT EDIT\nvalue = 5\n", encoding="utf-8"
    )
    git(
        "add",
        "scripts/probe.py",
        "migrations/probe.py",
        "tests/probe_generated.py",
        "tests/fake_generated_header.py",
    )
    git("commit", "--quiet", "-m", "head")
    (tmp_path / "tests" / "untracked.py").write_text("value = 6\n", encoding="utf-8")

    budget = _load_budget_module()
    files = budget.changed_python_files("HEAD~1")
    names = sorted(item.as_posix() for item in files)

    assert names == [
        "migrations/probe.py",
        "scripts/probe.py",
        "tests/fake_generated_header.py",
        "tests/untracked.py",
    ]
