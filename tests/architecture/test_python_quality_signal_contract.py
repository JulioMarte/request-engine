from __future__ import annotations

import sys
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "check_python_file_budget.py"


def _load_script() -> ModuleType:
    spec = spec_from_file_location("python_quality_signals_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Python quality signal scanner")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signals = _load_script()
effective_code_lines = cast(Callable[[str], int], signals.effective_code_lines)
file_candidate = cast(
    Callable[[Path, int, int | None], dict[str, object] | None], signals._file_loc_candidate
)
parse_c901 = cast(
    Callable[[list[dict[str, Any]]], list[dict[str, object]]], signals.parse_ruff_c901
)
render_feedback = cast(Callable[[dict[str, object]], str], signals.render_feedback)


def _fact(candidate: dict[str, object]) -> dict[str, object]:
    facts = cast(list[dict[str, object]], candidate["facts"])
    return facts[0]


def test_effective_loc_ignores_blank_and_comment_only_lines() -> None:
    source = "# comment\n\nvalue = 1  # inline\n\n# more\nreturn_value = value\n"
    assert effective_code_lines(source) == 2


def test_large_file_is_review_candidate_not_invariant_failure() -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 500, 90)
    assert candidate is not None
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert candidate["trigger_id"] == "QR-FSIZE-001"
    assert _fact(candidate) == {
        "kind": "effective_file_loc",
        "subject": "example.py",
        "value": 500,
        "tool": "python:tokenize",
        "interpretation": "none",
    }


def test_c901_json_becomes_evidence_without_semantic_claim() -> None:
    diagnostics = [
        {
            "code": "C901",
            "filename": "src/request_engine/example.py",
            "message": "`decide` is too complex (19 > 10)",
            "location": {"row": 17, "column": 1},
        }
    ]
    candidates = parse_c901(diagnostics)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert candidate["trigger_id"] == "QR-CPLX-001"
    assert _fact(candidate)["value"] == 19
    assert _fact(candidate)["interpretation"] == "none"


def test_feedback_tells_agents_how_not_to_game_the_metric() -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 500, 90)
    assert candidate is not None
    feedback = render_feedback({"candidates": [candidate]})
    for required in (
        "REVIEW_CANDIDATE",
        "NON-BLOCKING",
        "agent-semantic-review-playbook.md",
        "semantic-review-protocol.md",
        "Do NOT split files or extract helpers solely",
        "HEALTHY_AS_IS",
        "REFACTOR_RECOMMENDED",
        "rerun deterministic architecture",
        "INVARIANT_FAILURE cannot be overridden",
    ):
        assert required in feedback


def test_candidate_report_does_not_make_scanner_fail(monkeypatch: Any, tmp_path: Path) -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 500, 90)
    assert candidate is not None
    report = {"candidates": [candidate]}
    monkeypatch.setattr(signals, "build_report", lambda _base_ref: report)
    monkeypatch.setattr(signals, "write_report", lambda _report, _output: None)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(tmp_path / "signals.json")])
    assert signals.main() == 0
