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
    "v3-test-isolation.md",
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


def test_phase6_test_quality_and_stability_proofs_are_wired_to_ci() -> None:
    quality = ROOT / "scripts" / "release" / "audit_v3_test_quality.py"
    collection = ROOT / "scripts" / "release" / "prove_v3_test_collection.py"
    stability = ROOT / "scripts" / "release" / "prove_v3_concurrency_stability.py"
    order = ROOT / "scripts" / "release" / "prove_v3_test_order_independence.py"
    mutation = ROOT / "scripts" / "release" / "run_v3_mutation_probes.py"
    scratch_database = ROOT / "scripts" / "release" / "v3_scratch_database.py"
    _, jobs = _ci_sources()

    assert quality.is_file()
    assert collection.is_file()
    assert stability.is_file()
    assert order.is_file()
    assert mutation.is_file()
    assert scratch_database.is_file()
    assert "tests/e2e" in jobs
    assert "audit_v3_test_quality.py" in jobs
    assert "v3-test-quality.json" in jobs
    assert "prove_v3_test_collection.py" in jobs
    assert "v3-test-collection.json" in jobs
    assert "v3-tests-junit.xml" in jobs
    assert "prove_v3_concurrency_stability.py" in jobs
    assert "v3-concurrency-stability.json" in jobs
    assert "prove_v3_test_order_independence.py" in jobs
    assert "v3-test-order-independence.json" in jobs
    assert "v3-mutation-probes.json" in jobs


def test_phase6_repeated_test_proofs_use_fresh_v3_databases() -> None:
    release_scripts = ROOT / "scripts" / "release"
    isolated_proofs = (
        release_scripts / "prove_v3_concurrency_stability.py",
        release_scripts / "prove_v3_test_order_independence.py",
        release_scripts / "run_v3_mutation_probes.py",
    )

    for proof in isolated_proofs:
        source = proof.read_text(encoding="utf-8")
        assert "fresh_v3_database" in source, f"{proof.name} reuses a dirty database"
        assert re.search(r"env=(?:scratch_env|env)", source), (
            f"{proof.name} does not bind pytest to its scratch DB"
        )


def test_phase6_postgres_proofs_reset_data_between_tests() -> None:
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "isolate_postgres_test_data" in conftest
    assert 'get_closest_marker("postgres")' in conftest
    assert "TRUNCATE TABLE {} RESTART IDENTITY CASCADE" in conftest


def test_phase6_evidence_manifest_has_a_final_semantic_validity_gate() -> None:
    manifest = ROOT / "scripts" / "release" / "build_v3_evidence_manifest.py"
    workflow, jobs = _ci_sources()

    assert manifest.is_file()
    assert "evidence-manifest" in jobs
    assert "evidence-validity" in jobs
    assert "--require-valid" in jobs
    source = manifest.read_text(encoding="utf-8")
    assert '"evidence_status": candidate_status' in source
    assert '"release_status": "READY" if release_ready else "NOT_READY"' in source
    assert '"head_sha": head_sha' in source
    assert '"tested_sha": tested_sha' in source
    assert "_validate_junit" in source
    assert "artifact_validation" in source

    assert "postgres-v3-candidate-proof:" in workflow
    assert "if: ${{ always() }}" in workflow
    assert "scripts/ci/require_successful_needs.py" in workflow
