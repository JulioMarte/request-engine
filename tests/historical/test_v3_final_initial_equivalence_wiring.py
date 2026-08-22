from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
WRAPPER = ROOT / "scripts/ci/run_v3_candidate_with_g19.sh"
COMPATIBILITY_WRAPPER = ROOT / "scripts/ci/run_v3_frozen_compatibility.sh"
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
    assert "alembic upgrade 0001_initial" in structural
    assert "alembic upgrade head" not in structural
    assert 'PGDATABASE="${initial_db}" psql' not in structural
    assert "runpy.run_path" in builder
    assert "from migrations.v3_initial_payload import" not in builder
    assert "runpy.run_path" in revision
    assert "from migrations.v3_initial_payload import" not in revision
    assert "ClientCursor" in revision
    assert "bind.connection.driver_connection" in revision
    assert "sql.SQL(_load_v3_initial_sql())" in revision
    assert "bind.exec_driver_sql(_load_v3_initial_sql())" not in revision
    assert 'exec_driver_sql("RESET ALL")' in revision


def test_behavioral_equivalence_reuses_the_canonical_v3_tests_step() -> None:
    behavioral = BEHAVIORAL.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert 'SELECTOR = "ci_jobs:postgres-v3-candidate:v3-tests"' in behavioral
    assert "postgres-v3-candidate --step v3-tests" in behavioral
    assert 'V3_BASELINE_REVISION = "0001_initial"' in behavioral
    assert '["uv", "run", "alembic", "upgrade", V3_BASELINE_REVISION]' in behavioral
    assert '["uv", "run", "alembic", "upgrade", "head"]' not in behavioral
    assert '["uv", "run", "alembic", "current"]' in behavioral
    assert "final-initial database is not pinned to the released V3 revision" in behavioral
    assert "G17 initial SQL artifact differs from the reviewed Alembic payload" in behavioral
    assert '["psql", "--set=ON_ERROR_STOP=1"' not in behavioral
    assert "runpy.run_path" in behavioral
    assert "from migrations.v3_initial_payload import" not in behavioral
    producer = wrapper.index("prove_v3_final_initial_equivalence.py")
    finalizer = wrapper.index("finalize_v3_final_initial_equivalence_provenance.py")
    validator = wrapper.index("validate_v3_final_initial_equivalence_artifact_v2.py")
    assert producer < finalizer < validator


def test_post_baseline_ci_preserves_closed_v3_evidence_without_freezing_current_code() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    compatibility = COMPATIBILITY_WRAPPER.read_text(encoding="utf-8")
    compatibility_job = workflow.split("  postgres-v3-candidate-proof:", 1)[1].split(
        "  postgres-production-head:", 1
    )[0]

    assert "run_v3_frozen_compatibility.sh" in compatibility_job
    assert "run_v3_candidate_with_g19.sh" not in compatibility_job
    assert "v3-frozen-compatibility-proof" in compatibility_job
    assert 'RELEASED_V3_SHA="07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc"' in compatibility
    assert 'V3_BASELINE_REVISION="0001_initial"' in compatibility
    assert 'alembic upgrade "$V3_BASELINE_REVISION"' in compatibility
    assert "scripts/release/prove_v3_public_api_contract.py" in compatibility
    assert 'git worktree add --detach "$RELEASE_TREE" "$RELEASED_V3_SHA"' in compatibility
    assert "--step v3-tests" in compatibility
    assert "prove_v3_final_release.py" not in compatibility
    assert "build_v3_evidence_manifest.py" not in compatibility
    assert "migrations/versions/0001_initial.py" in compatibility
    assert "scripts/release/v3_public_api_contract_baseline.py" in compatibility


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
    assert "validate_v3_final_initial_equivalence_artifact_v2.py" in manifest
    assert "v3-initial-equivalence-candidate-schema.json" in manifest
    assert "v3-final-initial-tests-junit.xml" in manifest
