from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = "docs/engineering-quality/agent-semantic-review-playbook.md"
PROTOCOL = "docs/engineering-quality/semantic-review-protocol.md"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_normative_governance_treats_loc_and_c901_as_review_signals() -> None:
    governance = _read("docs/testing/repository-governance-contract.md")
    assert "120 effective-line hard maximum" not in governance
    assert "effective file LOC > 120  -> QR-FSIZE-001 REVIEW_CANDIDATE" in governance
    assert "Ruff C901 McCabe > 10" in governance
    assert "a `REVIEW_CANDIDATE` does **not** block merge by itself" in governance
    assert "`HEALTHY_AS_IS` is a valid semantic-review outcome" in governance
    assert "MUST NOT split files" in governance


def test_agent_control_plane_routes_quality_candidates_to_one_playbook() -> None:
    root_agents = _read("AGENTS.md")
    tests_agents = _read("tests/AGENTS.md")
    python_rules = _read(".github/instructions/python.instructions.md")
    copilot = _read(".github/copilot-instructions.md")
    for source in (root_agents, tests_agents, python_rules, copilot):
        assert PLAYBOOK in source
        assert "REVIEW_CANDIDATE" in source
        assert "HEALTHY_AS_IS" in source
    assert PROTOCOL in root_agents
    assert PROTOCOL in python_rules
    assert PROTOCOL in copilot


def test_agent_instructions_forbid_metric_gaming_and_llm_override() -> None:
    playbook = _read(PLAYBOOK)
    python_rules = _read(".github/instructions/python.instructions.md")
    for source in (playbook, python_rules):
        assert "solely" in source and "LOC" in source, (
            "Agent instructions must explicitly reject metric-only LOC remediation without "
            "freezing one exact sentence."
        )
        assert "INVARIANT_FAILURE" in source, (
            "Agent instructions must state that semantic review cannot waive deterministic "
            "architecture failures."
        )
        assert "INSUFFICIENT_CONTEXT" in source
        assert "comments" in source and "data" in source
        assert "rerun" in source.lower(), (
            "Agent instructions must require deterministic re-proof after remediation."
        )
    assert "Review phase — do not edit yet" in playbook
    assert "Re-proof phase — mandatory" in playbook


def test_c901_is_calibrated_but_not_part_of_blocking_global_ruff_selection() -> None:
    pyproject = cast(dict[str, Any], tomllib.loads(_read("pyproject.toml")))
    ruff = cast(dict[str, Any], pyproject["tool"])["ruff"]
    lint = cast(dict[str, Any], ruff)["lint"]
    selected = cast(list[str], cast(dict[str, Any], lint)["select"])
    mccabe = cast(dict[str, Any], cast(dict[str, Any], lint)["mccabe"])
    assert mccabe["max-complexity"] == 10
    assert "C901" not in selected, (
        "C901 is a calibration/review sensor. Do not add it to blocking global Ruff selection "
        "without satisfying the HARD-gate proof obligation."
    )


def test_old_hard_file_budget_instructions_are_absent_from_current_agent_surfaces() -> None:
    stale_phrases = (
        "120-line hard maximum",
        "blocks new/previously compliant files above 120",
        "oversized test files are ratcheted and may not grow",
    )
    current_surfaces = (
        _read("AGENTS.md"),
        _read("tests/AGENTS.md"),
        _read(".github/instructions/python.instructions.md"),
        _read(".github/copilot-instructions.md"),
    )
    for source in current_surfaces:
        for stale in stale_phrases:
            assert stale not in source
