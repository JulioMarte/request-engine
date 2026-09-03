from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = "docs/engineering-quality/agent-semantic-review-playbook.md"
PROTOCOL = "docs/engineering-quality/semantic-review-protocol.md"

AGENT_INSTRUCTION_FILES = (
    "AGENTS.md",
    "tests/AGENTS.md",
    "docs/AGENTS.md",
    "src/request_engine/AGENTS.md",
    "src/request_engine/modules/AGENTS.md",
    "scripts/dev/AGENTS.md",
    ".github/copilot-instructions.md",
    ".github/instructions/python.instructions.md",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_normative_governance_treats_metrics_and_coupling_as_review_signals() -> None:
    governance = _read("docs/testing/repository-governance-contract.md")
    assert "120 effective-line hard maximum" not in governance
    assert "QR-FSIZE-001 REVIEW_CANDIDATE" in governance
    assert "Ruff C901 McCabe > 10" in governance
    assert "QR-COUPLING-001 REVIEW_CANDIDATE" in governance
    assert "fan-in" in governance and "fan-out" in governance
    assert "no `fan-out > N = failure`" in governance
    assert "a `REVIEW_CANDIDATE` does **not** block merge by itself" in governance
    assert "`HEALTHY_AS_IS` is a valid semantic-review outcome" in governance
    assert "MUST NOT split files" in governance
    assert "hide a real dependency" in governance


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
    assert "QR-COUPLING-001" in python_rules
    assert "QR-COUPLING-001" in copilot


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
    assert "service locator" in python_rules
    assert "fan-out" in python_rules


def test_c901_is_calibrated_but_not_part_of_blocking_global_ruff_selection() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    lint = pyproject["tool"]["ruff"]["lint"]
    selected = lint["select"]
    mccabe = lint["mccabe"]
    assert mccabe["max-complexity"] == 10
    assert "C901" not in selected, (
        "C901 is a calibration/review sensor. Do not add it to blocking global Ruff selection "
        "without satisfying the HARD-gate proof obligation."
    )


def test_old_hard_file_budget_instructions_are_absent_from_current_agent_surfaces() -> None:
    stale_phrases = (
        "120-line hard maximum",
        "hard max 120 effective lines",
        "hard maximum = 120",
        "blocks new/previously compliant files above 120",
        "fail the canonical Python quality job",
        "oversized test files are ratcheted and may not grow",
    )
    current_surfaces = tuple(_read(path) for path in AGENT_INSTRUCTION_FILES)
    for source in current_surfaces:
        for stale in stale_phrases:
            assert stale not in source, (
                f"Agent instruction files must not state the retired hard file budget as "
                f"current. Found stale phrase: {stale!r}"
            )


def test_retired_quality_gates_are_never_presented_as_current_in_agent_instructions() -> None:
    """Protect the agent control plane from resurrecting retired quality gates.

    Protected guarantee: instruction files are the agent control plane; a retired
    gate presented as current blocking authority makes agents obey a rule that no
    longer exists (observed defect: the playbook taught the retired QR-MEGA-001
    HARD circuit breaker after its retirement).
    Plausible defect that must fail: restoring stale prose such as
    'QR-MEGA-001 is a scoped HARD circuit breaker' into any instruction file.
    """
    retired_rule_ids = ("QR-MEGA-001",)
    blocking_phrases = (
        "INVARIANT_FAILURE",
        "HARD",
        "circuit breaker",
        "blocks",
        "must not exceed",
    )
    retirement_markers = ("retired", "former", "no longer", "superseded", "historical")
    for path in AGENT_INSTRUCTION_FILES:
        for line_no, line in enumerate(_read(path).splitlines(), start=1):
            if not any(rule in line for rule in retired_rule_ids):
                continue
            lowered = line.lower()
            if not any(phrase.lower() in lowered for phrase in blocking_phrases):
                continue
            assert any(marker in lowered for marker in retirement_markers), (
                f"{path}:{line_no} presents the retired QR-MEGA-001 gate as current "
                "blocking authority. If the rule is retired, the line must carry a "
                "retirement marker; reinstating the gate requires the HARD-gate proof "
                "obligation and an explicit normative decision, never an instruction "
                "edit."
            )


def test_agent_instruction_file_inventory_is_fail_closed() -> None:
    """The detector must fail closed when an instruction surface moves or vanishes."""
    expected_files = (
        "AGENTS.md",
        "tests/AGENTS.md",
        "docs/AGENTS.md",
        "src/request_engine/AGENTS.md",
        "src/request_engine/modules/AGENTS.md",
        "scripts/dev/AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/instructions/python.instructions.md",
    )
    assert expected_files == AGENT_INSTRUCTION_FILES
    for path in AGENT_INSTRUCTION_FILES:
        assert (ROOT / path).is_file(), f"agent instruction surface missing: {path}"
