from copy import deepcopy

from scripts.release.v3_adversarial_manifest import (
    REQUIRED_FAMILIES,
    REQUIRED_RACES,
    REQUIRED_SUPPORTING_ARTIFACTS,
    validate_adversarial_failure,
)


def _valid_payload() -> dict[str, object]:
    families = [
        {
            "id": family_id,
            "status": "PASS",
            "owners": [f"tests/{family_id}.py"],
            "expected_owner_count": 1,
            "observed_owner_count": 1,
            "failures": [],
        }
        for family_id in sorted(REQUIRED_FAMILIES)
    ]
    races = [
        {
            "id": race_id,
            "status": "PASS",
            "owners": [f"tests/{race_id}.py"],
            "required_node_selectors": [f"tests/{race_id}.py::test_{race_id.lower()}"],
            "expected_owner_count": 1,
            "observed_owner_count": 1,
            "expected_node_selector_count": 1,
            "observed_node_selector_count": 1,
        }
        for race_id in sorted(REQUIRED_RACES)
    ]
    return {
        "schema_version": 1,
        "status": "PASS",
        "source": {
            "head_sha": "a" * 40,
            "tested_sha": "b" * 40,
            "checkout_sha": "c" * 40,
            "tree_sha": "d" * 40,
        },
        "environment": {"python": "3.13", "postgres_major": 18},
        "expected_family_count": 6,
        "observed_family_count": 6,
        "families": families,
        "expected_race_count": 29,
        "observed_race_count": 29,
        "races": races,
        "supporting_artifacts": {
            name: {"status": "PASS"} for name in sorted(REQUIRED_SUPPORTING_ARTIFACTS)
        },
        "missing_evidence": [],
        "failures": [],
    }


def test_g18_manifest_semantics_accept_complete_artifact() -> None:
    assert validate_adversarial_failure(_valid_payload()) == []


def test_g18_manifest_semantics_reject_top_level_pass_with_missing_race() -> None:
    payload = _valid_payload()
    races = payload["races"]
    assert isinstance(races, list)
    races.pop()
    payload["observed_race_count"] = 28
    errors = validate_adversarial_failure(payload)
    assert "G18 observed_race_count is not 29" in errors
    assert "G18 race inventory does not match R01-R29" in errors


def test_g18_manifest_semantics_reject_incomplete_node_evidence() -> None:
    payload = _valid_payload()
    races = payload["races"]
    assert isinstance(races, list)
    first = races[0]
    assert isinstance(first, dict)
    first["observed_node_selector_count"] = 0
    errors = validate_adversarial_failure(payload)
    assert any("pytest node inventory is incomplete" in error for error in errors)


def test_g18_manifest_semantics_reject_non_pass_family_and_supporting_artifact() -> None:
    payload = _valid_payload()
    families = payload["families"]
    assert isinstance(families, list)
    family = families[0]
    assert isinstance(family, dict)
    family["status"] = "FAIL"
    supporting = payload["supporting_artifacts"]
    assert isinstance(supporting, dict)
    evidence = next(iter(supporting.values()))
    assert isinstance(evidence, dict)
    evidence["status"] = "FAIL"
    errors = validate_adversarial_failure(payload)
    assert any("family" in error and "is not PASS" in error for error in errors)
    assert any("supporting artifact" in error and "is not PASS" in error for error in errors)


def test_g18_manifest_semantics_reject_duplicate_ids() -> None:
    payload = _valid_payload()
    races = payload["races"]
    assert isinstance(races, list)
    duplicate = deepcopy(races[0])
    races.append(duplicate)
    errors = validate_adversarial_failure(payload)
    assert any("duplicate id" in error for error in errors)
