from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypedDict, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "docs" / "testing" / "current-guarantees.toml"

KNOWN_EVIDENCE = {
    "invariant",
    "contract",
    "fitness",
    "adversarial",
    "historical",
    "concurrency",
}
KNOWN_RISKS = {"security", "capacity", "provenance", "temporal"}


class Guarantee(TypedDict):
    id: str
    statement: str
    severity: str
    required_evidence: list[str]
    risk: list[str]


def _guarantees() -> list[Guarantee]:
    payload = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    return cast(list[Guarantee], payload["guarantees"])


def test_current_guarantee_inventory_has_unique_semantic_ids() -> None:
    guarantees = _guarantees()
    identifiers = [item["id"] for item in guarantees]

    assert identifiers
    assert len(identifiers) == len(set(identifiers))
    assert all(item["statement"].strip() for item in guarantees)


def test_current_guarantee_inventory_uses_declared_evidence_vocabulary() -> None:
    for guarantee in _guarantees():
        assert guarantee["severity"] in {"critical", "high", "medium"}
        assert guarantee["required_evidence"]
        assert set(guarantee["required_evidence"]) <= KNOWN_EVIDENCE
        assert set(guarantee["risk"]) <= KNOWN_RISKS

        if guarantee["severity"] == "critical" and "fitness" not in guarantee["required_evidence"]:
            assert "invariant" in guarantee["required_evidence"]


def test_current_guarantee_inventory_does_not_freeze_test_file_shape() -> None:
    source = INVENTORY.read_text(encoding="utf-8")

    # The durable registry names guarantees and evidence classes. Exact file
    # mappings belong to generated inventory/migration evidence, not this policy.
    assert "tests/" not in source
    for guarantee in _guarantees():
        assert "test" not in guarantee
        assert "path" not in guarantee
        assert "file" not in guarantee
