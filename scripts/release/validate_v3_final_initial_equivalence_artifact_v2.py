#!/usr/bin/env python3
"""Validate G17 schema-v2 provenance before delegating semantic checks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[2]
LEGACY_VALIDATOR = ROOT / "scripts/release/validate_v3_final_initial_equivalence_artifact.py"
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")


def _load_legacy_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("g17_legacy_semantic_validator", LEGACY_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load G17 semantic validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and HEX40.fullmatch(value) is not None


def validation_errors(
    payload: Any,
    *,
    expected_source_head_sha: str | None = None,
    expected_tested_sha: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["artifact must be a JSON object"]

    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if "head_sha" in payload:
        errors.append("legacy head_sha must not be present")

    source_head_sha = payload.get("source_head_sha")
    tested_sha = payload.get("tested_sha")
    if not _valid_sha(source_head_sha):
        errors.append("source_head_sha must be 40 lowercase hex characters")
    if not _valid_sha(tested_sha):
        errors.append("tested_sha must be 40 lowercase hex characters")

    freeze = payload.get("candidate_freeze")
    if not isinstance(freeze, dict):
        errors.append("candidate_freeze must be an object")
    elif freeze.get("current_head") != tested_sha:
        errors.append("candidate_freeze current_head does not match tested_sha")

    if expected_source_head_sha is not None:
        if not _valid_sha(expected_source_head_sha):
            errors.append("expected source head SHA is malformed")
        elif source_head_sha != expected_source_head_sha:
            errors.append("source_head_sha does not match PHASE6_HEAD_SHA")
    if expected_tested_sha is not None:
        if not _valid_sha(expected_tested_sha):
            errors.append("expected tested SHA is malformed")
        elif tested_sha != expected_tested_sha:
            errors.append("tested_sha does not match PHASE6_TESTED_SHA")

    legacy_payload = dict(payload)
    legacy_payload["schema_version"] = 1
    legacy_payload["head_sha"] = tested_sha
    legacy_payload.pop("source_head_sha", None)
    legacy_payload.pop("tested_sha", None)
    legacy = _load_legacy_validator()
    errors.extend(legacy.validation_errors(legacy_payload))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    errors = validation_errors(
        payload,
        expected_source_head_sha=os.environ.get("PHASE6_HEAD_SHA"),
        expected_tested_sha=os.environ.get("PHASE6_TESTED_SHA"),
    )
    if errors:
        print("V3 final-initial equivalence artifact v2 is INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("V3 final-initial equivalence artifact v2 is VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
