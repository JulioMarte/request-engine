from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/ci/run_v3_candidate_with_g19.sh"
STRUCTURAL = ROOT / "scripts/db/prove_v3_initial_equivalence.sh"
BUILDER = ROOT / "scripts/db/build_v3_initial_candidate.py"
BEHAVIORAL = ROOT / "scripts/release/prove_v3_final_initial_equivalence.py"
MANIFEST = ROOT / "scripts/release/build_v3_evidence_manifest.py"
BASELINE_REVISION = ROOT / "migrations/versions/0001_initial.py"


def test_clean_structural_equivalence_runs_before_runtime_identity_provisioning() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    structural = wrapper.index("prove_v3_initial_equivalence.sh")
    runtime = wrapper.index("provision_v3_release_runtime.py", structural)

    assert structural < runtime
    assert "V3_EQUIVALENCE_CANDIDATE_SCHEMA_OUTPUT" in wrapper
    assert "V3_EQUIVALENCE_INITIAL_SCHEMA_OUTPUT" in wrapper
    assert "--step initial-equivalence" not in wrapper


def test_structural_equivalence_executes_the_reviewed_alembic_baseline() -> None:
    structural = STRUCTURAL.read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8")
    revision = BASELINE_REVISION.read_text(encoding="utf-8")

    assert "--require-reviewed-baseline" in structural
    assert "MIGRATION_DATABASE_URL" in structural
    assert "alembic upgrade head" in structural
    assert 'PGDATABASE="${initial_db}" psql' not in structural
    assert "runpy.run_path" in builder
    assert "from migrations.v3_initial_payload import" not in builder
    assert "runpy.run_path" in revision
    assert "from migrations.v3_initial_payload import" not in revision
    assert 'exec_driver_sql("RESET ALL")' in revision


def test_behavioral_equivalence_reuses_the_canonical_v3_tests_step() -> None:
    behavioral = BEHAVIORAL.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert 'SELECTOR = "ci_jobs:postgres-v3-candidate:v3-tests"' in behavioral
    assert "postgres-v3-candidate --step v3-tests" in behavioral
    assert '["uv", "run", "alembic", "upgrade", "head"]' in behavioral
    assert "G17 initial SQL artifact differs from the reviewed Alembic payload" in behavioral
    assert '["psql", "--set=ON_ERROR_STOP=1"' not in behavioral
    assert "runpy.run_path" in behavioral
    assert "from migrations.v3_initial_payload import" not in behavioral
    assert "prove_v3_final_initial_equivalence.py" in wrapper
    assert "validate_v3_final_initial_equivalence_artifact.py" in wrapper


def test_structural_proof_only_exports_artifacts_after_catalog_equality() -> None:
    structural = STRUCTURAL.read_text(encoding="utf-8")

    equality = structural.index('diff --unified "${work_dir}/candidate.json"')
    export_sql = structural.index('copy_artifact "$initial_sql"')
    export_candidate = structural.index('copy_artifact "${work_dir}/candidate.json"')
    export_initial = structural.index('copy_artifact "${work_dir}/initial.json"')

    assert equality < export_sql < export_candidate < export_initial


def test_manifest_uses_structured_g17_proof_instead_of_log_marker() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert 'artifact_validation["initial_equivalence"] = g17' in manifest
    assert "validate_v3_final_initial_equivalence_artifact.py" in manifest
    assert "v3-initial-equivalence-candidate-schema.json" in manifest
    assert "v3-final-initial-tests-junit.xml" in manifest
