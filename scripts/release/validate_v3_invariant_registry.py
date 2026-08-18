from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/release/v3-invariant-matrix.md"
GATES = ROOT / "docs/release/v3-release-gates.md"
REGISTRY = ROOT / "docs/release/v3-invariant-proof-registry.json"
EXPECTED_IDS = [f"V3-I{i:02d}" for i in range(1, 67)]
ALLOWED_STATUSES = {"PASS", "PARTIAL"}


def _matrix_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| V3-I"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"malformed invariant matrix row: {line}")
        invariant_id, owner, _evidence, status, _phase = cells
        rows[invariant_id] = (owner, status)
    return rows


def _g05_status() -> str:
    match = re.search(
        r"^\| G05 \|[^|]*\| (PASS|PARTIAL|MISSING|BLOCKED) \|",
        GATES.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("G05 row is missing from the release gate registry")
    return match.group(1)


def _load_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invariant proof registry must be a JSON object")
    return payload


def _requires_postgres(owner: str) -> bool:
    normalized = owner.lower()
    return any(
        token in normalized for token in ("db", "both", "transaction", "lock", "primitive", "ops")
    )


def validate_registry() -> list[str]:
    errors: list[str] = []
    matrix = _matrix_rows()
    payload = _load_registry()

    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    evidence_sets = payload.get("evidence_sets")
    if not isinstance(evidence_sets, dict) or not evidence_sets:
        errors.append("evidence_sets must be a non-empty object")
        evidence_sets = {}

    entries = payload.get("invariants")
    if not isinstance(entries, list):
        return [*errors, "invariants must be a list"]

    parsed_entries: list[tuple[str, str, str, str]] = []
    for index, entry in enumerate(entries, start=1):
        if (
            not isinstance(entry, list)
            or len(entry) != 4
            or not all(isinstance(value, str) for value in entry)
        ):
            errors.append(f"entry {index} must be [invariant_id, owner, status, evidence_set]")
            continue
        parsed_entries.append((entry[0], entry[1], entry[2], entry[3]))

    ids = [entry[0] for entry in parsed_entries]
    if len(entries) != len(EXPECTED_IDS):
        errors.append(f"registry must contain exactly {len(EXPECTED_IDS)} invariants")
    if ids != EXPECTED_IDS:
        errors.append("registry IDs must be exactly V3-I01..V3-I66 in canonical order")
    if len(set(ids)) != len(ids):
        errors.append("registry contains duplicate invariant IDs")
    if sorted(matrix) != EXPECTED_IDS:
        errors.append("Markdown invariant matrix is not exactly V3-I01..V3-I66")

    referenced_sets: set[str] = set()
    for invariant_id, owner, status, evidence_set in parsed_entries:
        if invariant_id not in matrix:
            errors.append(f"{invariant_id}: not present in invariant matrix")
            continue
        matrix_owner, matrix_status = matrix[invariant_id]
        if owner != matrix_owner:
            errors.append(f"{invariant_id}: owner {owner!r} does not match matrix {matrix_owner!r}")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{invariant_id}: invalid proof status {status!r}")
        if status != matrix_status:
            errors.append(
                f"{invariant_id}: registry status {status!r} "
                f"does not match matrix {matrix_status!r}"
            )

        referenced_sets.add(evidence_set)
        evidence = evidence_sets.get(evidence_set)
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{invariant_id}: evidence set {evidence_set!r} is missing/empty")
            continue
        if len(evidence) != len(set(evidence)):
            errors.append(f"{invariant_id}: evidence set {evidence_set!r} has duplicates")

        postgres_boundary_proven = False
        for proof in evidence:
            if not isinstance(proof, str):
                errors.append(f"{invariant_id}: evidence entries must be strings")
                continue
            if not proof.startswith("tests/") or not proof.endswith(".py"):
                errors.append(f"{invariant_id}: evidence path must name a Python test: {proof}")
                continue
            path = ROOT / proof
            if not path.is_file():
                errors.append(f"{invariant_id}: evidence path does not exist: {proof}")
                continue
            if "pytest.mark.postgres" in path.read_text(encoding="utf-8"):
                postgres_boundary_proven = True

        if _requires_postgres(owner) and not postgres_boundary_proven:
            errors.append(f"{invariant_id}: owner {owner!r} requires a real PostgreSQL proof")

    unused_sets = sorted(set(evidence_sets) - referenced_sets)
    if unused_sets:
        errors.append("unused evidence sets: " + ", ".join(unused_sets))

    if _g05_status() == "PASS":
        incomplete = [
            invariant_id
            for invariant_id, _owner, status, _evidence_set in parsed_entries
            if status != "PASS"
        ]
        if incomplete:
            errors.append(
                "G05 is PASS but invariant proof registry is incomplete: " + ", ".join(incomplete)
            )

    return errors


def main() -> int:
    errors = validate_registry()
    if errors:
        print("V3 invariant proof registry is INVALID.")
        for error in errors:
            print(f"- {error}")
        return 1
    print("V3 invariant proof registry is structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
