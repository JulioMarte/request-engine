from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/release/build_v3_evidence_manifest.py"
RUNNER = ROOT / "scripts/ci/run_v3_candidate_with_g19.sh"
PRODUCER = ROOT / "scripts/release/prove_v3_final_release.py"
VALIDATOR = ROOT / "scripts/release/validate_v3_final_release_artifact.py"


def test_g20_uses_preflight_then_independent_proof_then_final_manifest() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    preflight = runner.index("--preflight")
    producer = runner.index("scripts/release/prove_v3_final_release.py")
    validator = runner.index("scripts/release/validate_v3_final_release_artifact.py")
    final_manifest = runner.rindex("scripts/release/build_v3_evidence_manifest.py")

    assert preflight < producer < validator < final_manifest
    assert 'G20_PREFLIGHT=".phase6/v3-evidence-preflight.json"' in runner
    assert 'G20_PROOF=".phase6/v3-final-release-proof.json"' in runner
    final_command = runner[final_manifest:]
    assert "--require-ready" in final_command
    assert "--require-valid" not in final_command


def test_final_manifest_requires_semantically_valid_g20_artifact_for_ready() -> None:
    source = MANIFEST.read_text(encoding="utf-8")
    assert 'artifact_validation["final_release"] = g20' in source
    assert 'g20["status"] == "PASS"' in source
    assert "_RELEASE_READY(candidate_status, gate_statuses)" in source
    assert 'manifest["release_status"] = "READY" if release_ready else "NOT_READY"' in source
    assert "include_final_release_proof=not args.preflight" in source
    assert "if args.require_ready" in source
    assert "_TEST_QUALITY_PATH" in source
    assert "G20 test quality summary does not match test-quality artifact" in source


def test_g20_producer_and_validator_are_separate_fail_closed_scripts() -> None:
    producer = PRODUCER.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    assert "v3-final-release-proof" in producer
    assert "v3-final-release-proof" in validator
    assert "PHASE6_HEAD_SHA" in producer
    assert "PHASE6_TESTED_SHA" in producer
    assert "working_tree_dirty" in producer
    assert "REQUIRED_EVIDENCE" in producer
    assert "REQUIRED_EVIDENCE" in validator
    assert "TEST_QUALITY_PATH" in producer
    assert '"test_quality_warning_free"' in producer
    assert 'test_quality_summary["warning_count"] == 0' in producer
    assert "test quality summary reports warnings" in validator
    assert "preflight release status must be NOT_READY" in validator
    assert "G20 status is neither MISSING nor PASS" in validator
