from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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


def test_new_or_compliant_file_cannot_cross_hard_max() -> None:
    budget = _load_budget_module()
    path = Path("src/request_engine/example.py")

    assert budget.violation(path, 120, None) is None
    assert budget.violation(path, 121, None) is not None
    assert budget.violation(path, 121, 120) is not None


def test_existing_oversized_file_is_ratcheted_not_rewritten() -> None:
    budget = _load_budget_module()
    path = Path("tests/example.py")

    assert budget.violation(path, 140, 140) is None
    assert budget.violation(path, 130, 140) is None
    assert budget.violation(path, 141, 140) is not None
