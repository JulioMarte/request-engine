#!/usr/bin/env python3
"""Canonical V3 evidence manifest with mandatory G17 and G19 semantic proofs."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

_BASE_PATH = Path(__file__).with_name("build_v3_evidence_manifest_base.py")
_BASE = runpy.run_path(str(_BASE_PATH))

# Preserve the established manifest validator API used by architecture tests and
# release tooling while layering the later release-gate artifacts on top.
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
_VALIDATE_G17 = cast(
    Callable[[Any], list[str]],
    runpy.run_path(
        str(Path(__file__).with_name("validate_v3_final_initial_equivalence_artifact.py"))
    )["validation_errors"],
)
_VALIDATE_FREEZE = cast(
    Callable[[Any], list[str]],
    runpy.run_path(str(Path(__file__).with_name("validate_v3_candidate_freeze_artifact.py")))[
        "validation_errors"
    ],
)
_VALIDATE_G19 = cast(
    Callable[[dict[str, Any]], list[str]],
    runpy.run_path(
        str(Path(__file__).with_name("validate_v3_production_like_bootstrap_artifact.py"))
    )["validate_production_like_bootstrap"],
)

_G17_PATH = ROOT / ".phase6/v3-final-initial-equivalence.json"
_FREEZE_PATH = ROOT / ".phase6/v3-candidate-freeze.json"
_INITIAL_SQL_PATH = ROOT / ".phase6/0001_initial.candidate.sql"
_CANDIDATE_SCHEMA_PATH = ROOT / ".phase6/v3-initial-equivalence-candidate-schema.json"
_INITIAL_SCHEMA_PATH = ROOT / ".phase6/v3-final-initial-schema.json"
_CANDIDATE_JUNIT_PATH = ROOT / ".phase6/v3-tests-junit.xml"
_INITIAL_JUNIT_PATH = ROOT / ".phase6/v3-final-initial-tests-junit.xml"
_INITIAL_RUNTIME_PATH = ROOT / ".phase6/v3-final-initial-runtime.json"
_INITIAL_EQUIVALENCE_LOG = ROOT / ".phase6/v3-initial-equivalence.txt"
_G19_PATH = ROOT / ".phase6/v3-production-like-bootstrap-proof.json"


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_result(
    path: Path,
    validator: Callable[[Any], list[str]],
) -> dict[str, Any]:
    digest = _SHA256(path)
    if digest is None:
        return {"status": "MISSING", "sha256": None, "errors": ["artifact is missing"]}
    try:
        errors = validator(_LOAD_JSON(path))
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        errors = [f"could not parse artifact: {exc}"]
    return {"status": "PASS" if not errors else "FAIL", "sha256": digest, "errors": errors}


def _validate_freeze_artifact(path: Path = _FREEZE_PATH) -> dict[str, Any]:
    return _artifact_result(path, _VALIDATE_FREEZE)


def _validate_g17_artifact(path: Path = _G17_PATH) -> dict[str, Any]:
    digest = _SHA256(path)
    if digest is None:
        return {"status": "MISSING", "sha256": None, "errors": ["artifact is missing"]}
    try:
        payload = _LOAD_JSON(path)
        errors = _VALIDATE_G17(payload)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "sha256": digest,
            "errors": [f"could not parse artifact: {exc}"],
        }

    freeze = _validate_freeze_artifact()
    if freeze["status"] != "PASS":
        errors.append("candidate freeze artifact is not independently valid")
    freeze_summary = payload.get("candidate_freeze")
    if isinstance(freeze_summary, dict) and freeze["sha256"] != freeze_summary.get(
        "artifact_sha256"
    ):
        errors.append("candidate freeze digest does not match the G17 proof")

    initial_sql_digest = _SHA256(_INITIAL_SQL_PATH)
    if initial_sql_digest is None:
        errors.append("final-initial SQL artifact is missing")
    elif initial_sql_digest != payload.get("initial_sql_sha256"):
        errors.append("final-initial SQL digest does not match the G17 proof")

    structural = payload.get("structural")
    if isinstance(structural, dict):
        for label, actual_path in (
            ("candidate", _CANDIDATE_SCHEMA_PATH),
            ("initial", _INITIAL_SCHEMA_PATH),
        ):
            record = structural.get(label)
            actual_digest = None
            if actual_path.exists():
                actual_digest = _canonical_sha256(_LOAD_JSON(actual_path))
            if actual_digest is None:
                errors.append(f"{label} schema fingerprint artifact is missing")
            elif not isinstance(record, dict) or record.get("sha256") != actual_digest:
                errors.append(f"{label} schema fingerprint digest does not match G17 proof")

    behavioral = payload.get("behavioral")
    if isinstance(behavioral, dict):
        for label, actual_path in (
            ("candidate", _CANDIDATE_JUNIT_PATH),
            ("initial", _INITIAL_JUNIT_PATH),
        ):
            record = behavioral.get(label)
            actual_digest = _SHA256(actual_path)
            if actual_digest is None:
                errors.append(f"{label} JUnit artifact is missing")
            elif not isinstance(record, dict) or record.get("junit_sha256") != actual_digest:
                errors.append(f"{label} JUnit digest does not match G17 proof")

    runtime = payload.get("runtime")
    runtime_digest = _SHA256(_INITIAL_RUNTIME_PATH)
    if runtime_digest is None:
        errors.append("final-initial runtime proof artifact is missing")
    elif not isinstance(runtime, dict) or runtime.get("artifact_sha256") != runtime_digest:
        errors.append("final-initial runtime proof digest does not match G17 proof")

    return {"status": "PASS" if not errors else "FAIL", "sha256": digest, "errors": errors}


def _validate_g19_artifact(path: Path = _G19_PATH) -> dict[str, Any]:
    return _artifact_result(path, _VALIDATE_G19)


def build_manifest() -> dict[str, Any]:
    """Build the canonical manifest with mandatory G17 and G19 semantic artifacts."""

    manifest = _BASE_BUILD_MANIFEST()
    artifact_validation = cast(dict[str, dict[str, Any]], manifest["artifact_validation"])
    freeze = _validate_freeze_artifact()
    g17 = _validate_g17_artifact()
    g19 = _validate_g19_artifact()

    # The historical base manifest validated the initial-equivalence text log by
    # marker. G17 replaces that shallow check with the structured semantic proof.
    artifact_validation["candidate_freeze"] = freeze
    artifact_validation["initial_equivalence"] = g17
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

    artifacts = cast(dict[str, Any], manifest["artifacts"])
    artifacts["candidate_freeze_sha256"] = freeze["sha256"]
    artifacts["initial_equivalence_sha256"] = g17["sha256"]
    artifacts["initial_equivalence_log_sha256"] = _SHA256(_INITIAL_EQUIVALENCE_LOG)
    artifacts["production_like_bootstrap_sha256"] = g19["sha256"]
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
