import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "docs" / "release"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CI_JOBS = ROOT / "scripts" / "ci" / "ci_jobs.py"
REQUIRED_RELEASE_DOCS = {
    "v3-freeze-scope.md",
    "v3-release-gates.md",
    "v3-invariant-matrix.md",
    "v3-race-matrix.md",
    "v3-6a-baseline.md",
    "v3-bootstrap-proof.md",
    "v3-schema-fingerprint.md",
}
EXPECTED_GATES = [f"G{number:02d}" for number in range(1, 21)]
EXPECTED_INVARIANTS = [f"V3-I{number:02d}" for number in range(1, 62)]


def test_phase6_release_inventory_is_present() -> None:
    present = {path.name for path in RELEASE_DIR.glob("*.md")}
    assert present >= REQUIRED_RELEASE_DOCS


def test_phase6_gate_registry_declares_all_release_gates_once() -> None:
    text = (RELEASE_DIR / "v3-release-gates.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (G\d{2}) \|", text, flags=re.MULTILINE)
    assert rows == EXPECTED_GATES


def test_phase6_invariant_inventory_covers_canonical_v3_invariants_once() -> None:
    text = (RELEASE_DIR / "v3-invariant-matrix.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (V3-I\d{2}) \|", text, flags=re.MULTILINE)
    assert rows == EXPECTED_INVARIANTS


def test_phase6_scope_keeps_initial_migration_blocked_until_proof() -> None:
    text = (RELEASE_DIR / "v3-freeze-scope.md").read_text(encoding="utf-8")
    assert "Do not create or bless `0001_initial` before" in text
    assert "Do not freeze indexes before" in text
    assert "Do not remove the V3 candidate chain until" in text


def _ci_sources() -> tuple[str, str]:
    return (
        CI_WORKFLOW.read_text(encoding="utf-8"),
        CI_JOBS.read_text(encoding="utf-8"),
    )


def test_phase6_repeated_bootstrap_proof_is_wired_to_ci() -> None:
    script = ROOT / "scripts" / "db" / "prove_v3_candidate_bootstrap.sh"
    workflow, jobs = _ci_sources()

    assert script.is_file()
    assert "postgres-v3-bootstrap-proof:" in workflow
    assert "scripts/ci/ci_jobs.py postgres-v3-bootstrap-proof" in workflow
    assert "scripts/db/prove_v3_candidate_bootstrap.sh" in jobs


def test_phase6_schema_fingerprint_and_catalog_audit_are_wired_to_ci() -> None:
    fingerprint = ROOT / "scripts" / "db" / "v3_schema_fingerprint.py"
    audit = ROOT / "scripts" / "db" / "audit_v3_catalog.py"
    workflow, jobs = _ci_sources()

    assert fingerprint.is_file()
    assert audit.is_file()
    assert "scripts/ci/ci_jobs.py postgres-v3-candidate" in workflow
    assert "scripts/db/v3_schema_fingerprint.py" in jobs
    assert "scripts/db/audit_v3_catalog.py" in jobs
    assert "v3-candidate-release-proof" in workflow
