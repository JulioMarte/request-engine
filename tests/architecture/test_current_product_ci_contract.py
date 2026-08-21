from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_RUNNER = ROOT / "scripts" / "ci" / "run_current_product.sh"
F1_COMPAT_RUNNER = ROOT / "scripts" / "ci" / "run_f1_operational_profile.sh"
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


def test_workflow_separates_current_product_from_historical_provenance() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    current_job = workflow.split("  postgres-production-head:\n", 1)[1].split(
        "  postgres-v3-candidate:\n", 1
    )[0]
    historical_job = workflow.split("  postgres-v3-candidate-proof:\n", 1)[1].split(
        "  postgres-production-head:\n", 1
    )[0]
    python_job = workflow.split("  python-quality:\n", 1)[1].split(
        "  observability-contract:\n", 1
    )[0]

    assert "bash scripts/ci/run_current_product.sh" in current_job
    assert ".ci/current-product/" in current_job
    assert "uv run pytest tests/historical" in historical_job
    assert "tests/historical" not in python_job
