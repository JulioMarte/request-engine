from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_RUNNER = ROOT / "scripts" / "ci" / "run_current_product.sh"
F1_COMPAT_RUNNER = ROOT / "scripts" / "ci" / "run_f1_operational_profile.sh"
CI_JOBS = ROOT / "scripts" / "ci" / "ci_jobs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_current_product_runner_follows_repository_alembic_head() -> None:
    source = CURRENT_RUNNER.read_text(encoding="utf-8")

    assert "uv run alembic heads" in source
    assert "uv run alembic upgrade head" in source
    assert "expected exactly one Alembic head" in source
    assert "SELECT version_num FROM alembic_version" in source
    assert "0002_f1_supply" not in source
    assert "EXPECTED_HEAD" not in source


def test_f1_runner_is_only_a_compatibility_alias_to_current_product() -> None:
    source = F1_COMPAT_RUNNER.read_text(encoding="utf-8")

    assert 'run_current_product.sh" "$@"' in source
    assert "0002_f1_supply" not in source
    assert "EXPECTED_HEAD" not in source
    assert "pytest" not in source


def test_workflow_has_one_current_postgres_product_proof_and_no_frozen_v3_lane() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    current_job = workflow.split("  postgres-production-head:\n", 1)[1].split(
        "  postgres-v3-candidate:\n", 1
    )[0]
    python_job = workflow.split("  python-quality:\n", 1)[1].split(
        "  observability-contract:\n", 1
    )[0]

    assert "bash scripts/ci/run_current_product.sh" in current_job
    assert ".ci/current-product/" in current_job
    assert "postgres-v3-candidate-proof:" not in workflow
    assert "postgres-v3-bootstrap-proof:" not in workflow
    assert "tests/historical" not in workflow
    assert "run_v3_frozen_compatibility.sh" not in workflow
    assert "tests/historical" not in python_job


def test_frozen_v3_runner_has_been_retired_from_current_repository() -> None:
    assert not (ROOT / "scripts/ci/run_v3_frozen_compatibility.sh").exists()
    assert not (ROOT / "tests/historical").exists()


def test_canonical_ci_job_registry_does_not_expose_retired_v3_release_jobs() -> None:
    source = CI_JOBS.read_text(encoding="utf-8")

    assert '"postgres-v3-bootstrap-proof"' not in source
    assert '"postgres-v3-candidate"' not in source
    assert "prove_v3_public_api_contract.py" not in source
    assert "build_v3_evidence_manifest.py" not in source


def test_python_quality_job_owns_maintainability_sensor_canonically() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ci_jobs = CI_JOBS.read_text(encoding="utf-8")
    python_job = workflow.split("  python-quality:\n", 1)[1].split(
        "  observability-contract:\n", 1
    )[0]

    assert '"file-budget"' in ci_jobs
    assert "check_python_file_budget.py" in ci_jobs
    assert "FILE_BUDGET_BASE_REF" in python_job
    assert "check_python_file_budget.py" not in python_job
    assert "python scripts/ci/ci_jobs.py python-quality" in python_job
