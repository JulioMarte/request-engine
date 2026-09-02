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
write_github_summary = cast(
    Callable[[dict[str, object], str, Path], None], signals.write_github_summary
)


def _fact(candidate: dict[str, object]) -> dict[str, object]:
    facts = cast(list[dict[str, object]], candidate["facts"])
    return facts[0]


def _coupling_snapshot(
    module: str,
    *,
    fan_in: int,
    outbound: list[str],
) -> dict[str, object]:
    return {
        "modules": [
            {
                "module": module,
                "fan_in": fan_in,
                "fan_out": len(outbound),
                "inbound_modules": [],
                "outbound_modules": outbound,
            }
        ],
        "edges": [{"source": module, "target": target} for target in outbound],
    }


def test_effective_loc_ignores_blank_and_comment_only_lines() -> None:
    source = "# comment\n\nvalue = 1  # inline\n\n# more\nreturn_value = value\n"
    assert effective_code_lines(source) == 2


def test_500_line_file_is_review_candidate_not_invariant_failure() -> None:
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


def test_501_line_file_remains_review_evidence_not_architecture_failure() -> None:
    candidate = file_candidate(
        Path("src/request_engine/modules/booking/application/large.py"), 501, 480
    )
    assert candidate is not None
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert candidate["trigger_id"] == "QR-FSIZE-001"
    assert _fact(candidate)["value"] == 501


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


def test_qr_nav_only_flags_new_obvious_indirection(monkeypatch: Any) -> None:
    def previous_file_count(_ref: str, _root: Path) -> int:
        return 10

    def current_file_count(_root: Path) -> int:
        return 11

    monkeypatch.setattr(signals, "_module_file_count", previous_file_count)
    monkeypatch.setattr(signals, "_current_module_file_count", current_file_count)
    observation: dict[str, object] = {
        "function_count": 1,
        "one_call_forwarder_count": 1,
        "forwarding_only_functions": True,
        "reexport_only_module": False,
        "interpretation": "none",
    }
    path = Path("src/request_engine/modules/booking/application/new_wrapper.py")
    candidate = signals._navigation_candidate(path, observation, is_new=True, base_ref="base")
    assert candidate is not None
    assert candidate["trigger_id"] == "QR-NAV-001"
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert signals._navigation_candidate(path, observation, is_new=False, base_ref="base") is None


def test_fan_out_growth_emits_nonblocking_coupling_review() -> None:
    base = _coupling_snapshot("recovery", fan_in=1, outbound=["booking", "communications"])
    current = _coupling_snapshot(
        "recovery",
        fan_in=1,
        outbound=["booking", "catalog", "communications", "queue"],
    )
    candidates = signals._coupling_candidates(base, current)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["classification"] == "REVIEW_CANDIDATE"
    assert candidate["trigger_id"] == "QR-COUPLING-001"
    facts = cast(list[dict[str, object]], candidate["facts"])
    assert facts[0]["kind"] == "module_fan_out"
    assert facts[0]["value"] == 4
    assert any(
        fact["kind"] == "added_outbound_modules" and fact["value"] == "catalog,queue"
        for fact in facts
    )


def test_high_fan_out_without_new_edges_does_not_create_numeric_cliff() -> None:
    outbound = ["a", "b", "c", "d", "e", "f", "g"]
    base = _coupling_snapshot("orchestrator", fan_in=3, outbound=outbound)
    current = _coupling_snapshot("orchestrator", fan_in=3, outbound=outbound)
    assert signals._coupling_candidates(base, current) == []


def test_feedback_tells_agents_how_not_to_game_the_metric() -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 501, 90)
    assert candidate is not None
    feedback = render_feedback({"candidates": [candidate]})
    for required in (
        "REVIEW_CANDIDATE",
        "NON-BLOCKING",
        "agent-semantic-review-playbook.md",
        "semantic-review-protocol.md",
        "Do NOT split files",
        "HEALTHY_AS_IS",
        "REFACTOR_RECOMMENDED",
        "rerun deterministic architecture",
    ):
        assert required in feedback


def test_successful_candidate_is_written_to_github_step_summary(
    monkeypatch: Any, tmp_path: Path
) -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 501, 90)
    assert candidate is not None
    report: dict[str, object] = {
        "schema_version": "quality-scan/v1",
        "candidates": [candidate],
        "module_coupling": {"added_edges": []},
    }
    feedback = render_feedback(report)
    summary_path = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_github_summary(report, feedback, Path(".ci/python-quality-signals.json"))

    summary = summary_path.read_text(encoding="utf-8")
    for required in (
        "Python maintainability signals",
        "Candidates:** 1",
        "Invariant failures:** 0",
        "New module dependency edges:** 0",
        "quality-scan/v1",
        "non-blocking",
        "REVIEW_CANDIDATE",
        "HEALTHY_AS_IS",
        "agent-semantic-review-playbook.md",
        ".ci/python-quality-signals.json",
    ):
        assert required in summary


def test_candidate_report_does_not_make_scanner_fail(monkeypatch: Any, tmp_path: Path) -> None:
    candidate = file_candidate(Path("src/request_engine/example.py"), 501, 90)
    assert candidate is not None
    report: dict[str, object] = {"candidates": [candidate]}

    def build_report_stub(_base_ref: str) -> dict[str, object]:
        return report

    def write_report_stub(_report: dict[str, object], _output: Path) -> None:
        return None

    def write_summary_stub(
        _report: dict[str, object], _feedback: str, _output: Path
    ) -> None:
        return None

    monkeypatch.setattr(signals, "build_report", build_report_stub)
    monkeypatch.setattr(signals, "write_report", write_report_stub)
    monkeypatch.setattr(signals, "write_github_summary", write_summary_stub)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(tmp_path / "signals.json")])
    assert signals.main() == 0
