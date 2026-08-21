from __future__ import annotations

import tomllib
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[2]
GUARANTEES = ROOT / "docs" / "testing" / "current-guarantees.toml"
PROOF_MAP = ROOT / "docs" / "testing" / "current-proof-map.toml"


class Guarantee(TypedDict):
    id: str
    required_evidence: list[str]


class Proof(TypedDict):
    guarantee: str
    path: str
    evidence: list[str]


def _guarantees() -> dict[str, Guarantee]:
    payload = tomllib.loads(GUARANTEES.read_text(encoding="utf-8"))
    entries = cast(list[Guarantee], payload["guarantees"])
    return {entry["id"]: entry for entry in entries}


def _proofs() -> list[Proof]:
    payload = tomllib.loads(PROOF_MAP.read_text(encoding="utf-8"))
    assert payload["normative"] is False
    return cast(list[Proof], payload["proofs"])


def test_current_proof_map_only_references_current_guarantees_and_existing_tests() -> None:
    guarantees = _guarantees()
    proofs = _proofs()

    assert proofs
    for proof in proofs:
        assert proof["guarantee"] in guarantees
        path = ROOT / proof["path"]
        assert path.is_file(), f"mapped proof does not exist: {proof['path']}"
        assert path.is_relative_to(ROOT / "tests")
        assert "historical" not in path.relative_to(ROOT / "tests").parts


def test_every_current_guarantee_has_representative_required_evidence() -> None:
    guarantees = _guarantees()
    proofs = _proofs()
    evidence_by_guarantee: dict[str, set[str]] = defaultdict(set)

    for proof in proofs:
        evidence_by_guarantee[proof["guarantee"]].update(proof["evidence"])

    gaps: list[str] = []
    for identifier, guarantee in guarantees.items():
        missing = set(guarantee["required_evidence"]) - evidence_by_guarantee[identifier]
        if missing:
            gaps.append(f"{identifier}: missing {sorted(missing)}")

    assert gaps == [], "current proof-map evidence gaps:\n" + "\n".join(gaps)


def test_proof_map_is_explicitly_migration_evidence_not_normative_shape() -> None:
    payload = tomllib.loads(PROOF_MAP.read_text(encoding="utf-8"))

    assert payload["status"] == "migration-current-proof-map"
    assert payload["normative"] is False
    assert payload["guarantees"] == "docs/testing/current-guarantees.toml"
