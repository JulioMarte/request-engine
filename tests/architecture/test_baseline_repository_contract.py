from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"


def test_initial_revision_uses_canonical_baseline_runtime() -> None:
    source = (MIGRATIONS / "versions" / "0001_initial.py").read_text(encoding="utf-8")

    assert ' / "baseline" / "loader.py"' in source
    assert "rebaseline_candidate" not in source
    assert "v3_initial_payload" not in source


def test_accepted_baseline_surface_is_canonical_and_transitional_surfaces_are_gone() -> None:
    baseline = MIGRATIONS / "baseline"

    assert (baseline / "manifest.json").is_file()
    assert (baseline / "loader.py").is_file()
    assert (baseline / "0001_roles.sql").is_file()
    assert list(baseline.glob("0001_schema.*.sql"))

    assert not (MIGRATIONS / "rebaseline_candidate").exists()
    assert not (MIGRATIONS / "v3_initial_payload.py").exists()
    assert not (MIGRATIONS / "sql" / "v3_initial").exists()
    assert not (MIGRATIONS / "sql" / "v3_candidate").exists()
    assert not (MIGRATIONS / "f2_steps").exists()
    assert not (MIGRATIONS / "s0d_steps").exists()


def test_baseline_integrity_proof_does_not_freeze_current_head_to_0001() -> None:
    runner = (ROOT / "scripts" / "ci" / "run_current_product.sh").read_text(encoding="utf-8")
    baseline_proof = ROOT / "scripts" / "db" / "prove_baseline_integrity.sh"

    assert baseline_proof.is_file()
    assert "prove_baseline_integrity.sh" in runner
    assert "uv run alembic heads" in runner
    assert "uv run alembic upgrade head" in runner
    assert "HEAD == 0001" not in runner

    retired = (
        "materialize_rebaseline_candidate.py",
        "prove_rebaseline_fresh_cluster.sh",
        "prove_rebaseline_reproduction.sh",
        "prove_rebaseline_single_alembic.sh",
        "render_role_bootstrap.py",
    )
    assert all(not (ROOT / "scripts" / "db" / name).exists() for name in retired)
