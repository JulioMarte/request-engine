#!/usr/bin/env python3
"""Finalize G17 provenance without conflating source and tested commits."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[2]
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not resolve tested checkout: {detail}")
    return result.stdout.strip()


def _require_sha(label: str, value: object) -> str:
    if not isinstance(value, str) or HEX40.fullmatch(value) is None:
        raise RuntimeError(f"{label} must be 40 lowercase hex characters")
    return value


def finalize_provenance(payload: Any, env: dict[str, str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("G17 artifact must be a JSON object")
    if payload.get("schema_version") != 1:
        raise RuntimeError("G17 producer artifact must use schema_version 1")
    if payload.get("proof") != "v3-final-initial-equivalence":
        raise RuntimeError("G17 producer artifact proof identifier is invalid")
    if payload.get("status") != "PASS" or payload.get("failures") != []:
        raise RuntimeError("refusing to finalize provenance for a non-PASS G17 artifact")

    actual_tested_sha = _require_sha("tested checkout SHA", _git_head())
    legacy_head_sha = _require_sha("legacy G17 head_sha", payload.get("head_sha"))
    if legacy_head_sha != actual_tested_sha:
        raise RuntimeError("legacy G17 head_sha does not match the tested checkout")

    expected_tested_sha = env.get("PHASE6_TESTED_SHA", actual_tested_sha)
    tested_sha = _require_sha("PHASE6_TESTED_SHA", expected_tested_sha)
    if tested_sha != actual_tested_sha:
        raise RuntimeError("PHASE6_TESTED_SHA does not match the tested checkout")

    source_head_sha = _require_sha(
        "PHASE6_HEAD_SHA",
        env.get("PHASE6_HEAD_SHA", tested_sha),
    )

    freeze = payload.get("candidate_freeze")
    if not isinstance(freeze, dict):
        raise RuntimeError("candidate_freeze must be an object")
    if freeze.get("current_head") != tested_sha:
        raise RuntimeError("candidate_freeze current_head does not match tested_sha")

    finalized = dict(payload)
    finalized["schema_version"] = 2
    finalized["source_head_sha"] = source_head_sha
    finalized["tested_sha"] = tested_sha
    finalized.pop("head_sha", None)
    return finalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.artifact.read_text(encoding="utf-8"))
        finalized = finalize_provenance(payload, os.environ.copy())
        temporary = args.artifact.with_suffix(args.artifact.suffix + ".tmp")
        temporary.write_text(
            json.dumps(finalized, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.artifact)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"V3 final-initial provenance finalization FAILED: {exc}")
        return 1
    print("V3 final-initial provenance finalization PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
