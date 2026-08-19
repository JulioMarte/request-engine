#!/usr/bin/env python3
"""Canonical V3 evidence manifest with mandatory G19 production-like proof."""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path
from typing import Any, Callable, cast

_BASE_PATH = Path(__file__).with_name("build_v3_evidence_manifest_base.py")
_BASE = runpy.run_path(str(_BASE_PATH))

# Preserve the established manifest validator API used by architecture tests and
# release tooling while keeping the pre-G19 implementation byte-for-byte intact.
for _name, _value in _BASE.items():
    if not _name.startswith("__") and _name not in {"build_manifest", "main", "parse_args"}:
        globals()[_name] = _value

ROOT = cast(Path, _BASE["ROOT"])
_BASE_BUILD_MANIFEST = cast(Callable[[], dict[str, Any]], _BASE["build_manifest"])
_SHA256 = cast(Callable[[Path], str | None], _BASE["_sha256"])
_LOAD_JSON = cast(Callable[[Path], dict[str, Any]], _BASE["_load_json"])
_RELEASE_READY = cast(
    Callable[[str, dict[str, str]], bool],
    _BASE["_release_ready"],
)
_VALIDATE_G19 = cast(
    Callable[[dict[str, Any]], list[str]],
    runpy.run_path(
        str(Path(__file__).with_name("validate_v3_production_like_bootstrap_artifact.py"))
    )["validate_production_like_bootstrap"],
)
_G19_PATH = ROOT / ".phase6/v3-production-like-bootstrap-proof.json"


def _validate_g19_artifact(path: Path = _G19_PATH) -> dict[str, Any]:
    digest = _SHA256(path)
    if digest is None:
        return {"status": "MISSING", "sha256": None, "errors": ["artifact is missing"]}
    try:
        errors = _VALIDATE_G19(_LOAD_JSON(path))
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        errors = [f"could not parse artifact: {exc}"]
    return {"status": "PASS" if not errors else "FAIL", "sha256": digest, "errors": errors}


def build_manifest() -> dict[str, Any]:
    """Build the canonical manifest and make G19 a mandatory semantic artifact."""

    manifest = _BASE_BUILD_MANIFEST()
    artifact_validation = cast(dict[str, dict[str, Any]], manifest["artifact_validation"])
    g19 = _validate_g19_artifact()
    artifact_validation["production_like_bootstrap"] = g19

    missing_artifacts = sorted(
        name for name, result in artifact_validation.items() if result["status"] == "MISSING"
    )
    validation_errors = [
        f"{name}: {error}"
        for name, result in artifact_validation.items()
        for error in result["errors"]
        if result["status"] == "FAIL"
    ]
    candidate_status = (
        "INCOMPLETE" if missing_artifacts else "INVALID" if validation_errors else "VALID"
    )

    manifest["artifact_set_complete"] = not missing_artifacts
    manifest["missing_artifacts"] = missing_artifacts
    manifest["validation_errors"] = validation_errors
    manifest["evidence_status"] = candidate_status

    gate_statuses = cast(dict[str, str], manifest["registries"]["gate_statuses"])
    release_ready = _RELEASE_READY(candidate_status, gate_statuses)
    manifest["release_ready"] = release_ready
    manifest["release_status"] = "READY" if release_ready else "NOT_READY"
    manifest["artifacts"]["production_like_bootstrap_sha256"] = g19["sha256"]
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-valid", action="store_true")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Deprecated alias for --require-valid; completeness alone is not accepted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    status = manifest["evidence_status"]
    if (args.require_valid or args.require_complete) and status != "VALID":
        print(f"V3 candidate evidence is {status}, not VALID.")
        for error in manifest["validation_errors"]:
            print(f"- {error}")
        if manifest["missing_artifacts"]:
            print(f"- missing: {', '.join(manifest['missing_artifacts'])}")
        return 1

    print(
        f"V3 candidate evidence manifest generated {status}; "
        f"overall release status is {manifest['release_status']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
