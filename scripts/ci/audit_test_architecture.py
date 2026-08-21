#!/usr/bin/env python3
"""Inventory Request Engine tests by physical scope and evidence metadata."""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

EVIDENCE_MARKERS = frozenset(
    {
        "invariant",
        "contract",
        "fitness",
        "adversarial",
        "historical",
        "security",
        "capacity",
        "provenance",
        "temporal",
    }
)

# These names describe exact release/freeze machinery rather than a live product
# invariant. This guard prevents obvious provenance tests from drifting back into
# the architecture-fitness lane after the migration.
HISTORICAL_ARCHITECTURE_HINTS = (
    "artifact_semantics",
    "adversarial_failure_proof",
    "candidate_freeze",
    "database_candidate",
    "evidence_manifest",
    "final_initial",
    "final_release",
    "invariant_proof_registry",
    "production_like_bootstrap",
    "public_contract_freeze",
    "release_harness",
    "release_inventory",
    "scratch_database_isolation",
)


def _configured_markers() -> set[str]:
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    entries = payload["tool"]["pytest"]["ini_options"]["markers"]
    return {str(entry).split(":", 1)[0].strip() for entry in entries}


def _explicit_pytest_markers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    markers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if not isinstance(value, ast.Attribute) or value.attr != "mark":
            continue
        if isinstance(value.value, ast.Name) and value.value.id == "pytest":
            markers.add(node.attr)
    return markers


def _scope(path: Path) -> str:
    relative = path.relative_to(TEST_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else "root"


def _effective_evidence_markers(scope: str, explicit: set[str]) -> set[str]:
    effective = set(explicit & EVIDENCE_MARKERS)
    if scope == "architecture":
        effective.add("fitness")
    elif scope == "historical":
        effective.add("historical")
    return effective


def build_inventory() -> tuple[dict[str, object], list[str]]:
    configured = _configured_markers()
    missing_markers = sorted(EVIDENCE_MARKERS - configured)

    tests: list[dict[str, object]] = []
    scope_counts: Counter[str] = Counter()
    marker_counts: Counter[str] = Counter()
    contamination: list[str] = []
    v3_named_current: list[str] = []
    feature_era_current: list[str] = []

    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        scope = _scope(path)
        explicit = _explicit_pytest_markers(path)
        explicit_evidence = explicit & EVIDENCE_MARKERS
        effective_evidence = _effective_evidence_markers(scope, explicit)

        scope_counts[scope] += 1
        marker_counts.update(effective_evidence)
        tests.append(
            {
                "path": relative,
                "scope": scope,
                "explicit_evidence_markers": sorted(explicit_evidence),
                "effective_evidence_markers": sorted(effective_evidence),
            }
        )

        if scope == "architecture" and any(
            hint in path.stem for hint in HISTORICAL_ARCHITECTURE_HINTS
        ):
            contamination.append(relative)
        if scope != "historical" and path.stem.startswith("test_v3_"):
            v3_named_current.append(relative)
        if scope != "historical" and any(part.startswith("f1_") for part in path.parts):
            feature_era_current.append(relative)

    failures: list[str] = []
    if missing_markers:
        failures.append(f"missing pytest evidence markers: {missing_markers}")
    if contamination:
        failures.append(
            "release-provenance tests remain in tests/architecture: " + ", ".join(contamination)
        )

    payload: dict[str, object] = {
        "schema_version": 1,
        "test_file_count": len(tests),
        "physical_scope_counts": dict(sorted(scope_counts.items())),
        "effective_evidence_marker_counts": dict(sorted(marker_counts.items())),
        "historical_architecture_contamination": contamination,
        "v3_named_current_files": v3_named_current,
        "feature_era_current_files": feature_era_current,
        "tests": tests,
    }
    return payload, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, failures = build_inventory()

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"test files: {payload['test_file_count']}")
    print(f"physical scopes: {payload['physical_scope_counts']}")
    print(f"evidence markers: {payload['effective_evidence_marker_counts']}")
    print(f"current v3-named files: {len(payload['v3_named_current_files'])}")
    print(f"feature-era current files: {len(payload['feature_era_current_files'])}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("test architecture inventory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
