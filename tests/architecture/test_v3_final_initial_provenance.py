import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
FINALIZER_PATH = ROOT / "scripts/release/finalize_v3_final_initial_equivalence_provenance.py"
VALIDATOR_PATH = ROOT / "scripts/release/validate_v3_final_initial_equivalence_artifact_v2.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


finalizer = _load("g17_provenance_finalizer", FINALIZER_PATH)
validator = _load("g17_provenance_validator_v2", VALIDATOR_PATH)


def _producer_payload(tested_sha: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "proof": "v3-final-initial-equivalence",
        "status": "PASS",
        "head_sha": tested_sha,
        "candidate_freeze": {"current_head": tested_sha},
        "failures": [],
    }


def test_finalizer_splits_source_head_from_tested_checkout(monkeypatch) -> None:
    source_sha = "1" * 40
    tested_sha = "2" * 40
    monkeypatch.setattr(finalizer, "_git_head", lambda: tested_sha)

    payload = finalizer.finalize_provenance(
        _producer_payload(tested_sha),
        {"PHASE6_HEAD_SHA": source_sha, "PHASE6_TESTED_SHA": tested_sha},
    )

    assert payload["schema_version"] == 2
    assert payload["source_head_sha"] == source_sha
    assert payload["tested_sha"] == tested_sha
    assert "head_sha" not in payload
    assert payload["candidate_freeze"]["current_head"] == tested_sha


def test_finalizer_rejects_tested_sha_that_is_not_the_checkout(monkeypatch) -> None:
    checkout_sha = "2" * 40
    monkeypatch.setattr(finalizer, "_git_head", lambda: checkout_sha)

    try:
        finalizer.finalize_provenance(
            _producer_payload(checkout_sha),
            {"PHASE6_HEAD_SHA": "1" * 40, "PHASE6_TESTED_SHA": "3" * 40},
        )
    except RuntimeError as exc:
        assert str(exc) == "PHASE6_TESTED_SHA does not match the tested checkout"
    else:
        raise AssertionError("mismatched tested SHA was accepted")


def test_finalizer_rejects_freeze_bound_to_another_checkout(monkeypatch) -> None:
    tested_sha = "2" * 40
    payload = _producer_payload(tested_sha)
    payload["candidate_freeze"] = {"current_head": "3" * 40}
    monkeypatch.setattr(finalizer, "_git_head", lambda: tested_sha)

    try:
        finalizer.finalize_provenance(
            payload,
            {"PHASE6_HEAD_SHA": "1" * 40, "PHASE6_TESTED_SHA": tested_sha},
        )
    except RuntimeError as exc:
        assert str(exc) == "candidate_freeze current_head does not match tested_sha"
    else:
        raise AssertionError("stale candidate freeze provenance was accepted")


def test_v2_validator_rejects_legacy_or_environment_mismatched_provenance() -> None:
    source_sha = "1" * 40
    tested_sha = "2" * 40
    payload = {
        "schema_version": 2,
        "source_head_sha": source_sha,
        "tested_sha": tested_sha,
        "candidate_freeze": {"current_head": tested_sha},
    }

    legacy = dict(payload)
    legacy["head_sha"] = tested_sha
    assert "legacy head_sha must not be present" in validator.validation_errors(legacy)

    errors = validator.validation_errors(
        payload,
        expected_source_head_sha="3" * 40,
        expected_tested_sha="4" * 40,
    )
    assert "source_head_sha does not match PHASE6_HEAD_SHA" in errors
    assert "tested_sha does not match PHASE6_TESTED_SHA" in errors
