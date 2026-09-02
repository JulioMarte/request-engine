from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import git  # noqa: E402

MEGA_FILE_HARD_LIMIT = 500
MEGA_EXCEPTION_REGISTRY = Path("docs/engineering-quality/mega-file-exceptions.v1.json")
CORE_MEGA_CATEGORIES = frozenset(
    {
        "production_api",
        "production_application",
        "production_composition",
        "production_contracts",
        "production_domain",
    }
)
REGISTRY_SCHEMA_VERSION = "mega-file-exceptions/v1"


def _validated_exception(entry: Any) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise ValueError("mega-file exception entries must be JSON objects")
    path = entry.get("path")
    max_effective_loc = entry.get("max_effective_loc")
    rationale = entry.get("rationale")
    approval_ref = entry.get("approval_ref")
    if not isinstance(path, str) or not path.endswith(".py"):
        raise ValueError("mega-file exception path must be an exact Python file path")
    if not isinstance(max_effective_loc, int) or max_effective_loc <= MEGA_FILE_HARD_LIMIT:
        raise ValueError("mega-file exception max_effective_loc must be greater than 500")
    if not isinstance(rationale, str) or len(rationale.strip()) < 40:
        raise ValueError("mega-file exception rationale must contain at least 40 characters")
    if not isinstance(approval_ref, str) or not approval_ref.strip():
        raise ValueError("mega-file exception approval_ref must identify the prior decision")
    return {
        "path": path,
        "max_effective_loc": max_effective_loc,
        "rationale": rationale.strip(),
        "approval_ref": approval_ref.strip(),
    }


def load_base_exceptions(base_ref: str) -> dict[str, dict[str, object]]:
    """Load only exceptions that already exist on the reviewed branch base."""
    result = git(
        "show",
        f"{base_ref}:{MEGA_EXCEPTION_REGISTRY.as_posix()}",
        check=False,
    )
    if result.returncode != 0:
        return {}
    payload: Any = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("mega-file exception registry must be a JSON object")
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"mega-file exception registry must use {REGISTRY_SCHEMA_VERSION}")
    raw_entries = payload.get("exceptions")
    if not isinstance(raw_entries, list):
        raise ValueError("mega-file exception registry must contain an exceptions list")
    exceptions: dict[str, dict[str, object]] = {}
    for raw_entry in raw_entries:
        entry = _validated_exception(raw_entry)
        path = str(entry["path"])
        if path in exceptions:
            raise ValueError(f"duplicate mega-file exception for {path}")
        exceptions[path] = entry
    return exceptions


def mega_file_failure(
    path: Path,
    *,
    category: str,
    current: int,
    previous: int | None,
    base_exceptions: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    """Return a blocking finding only for anomalous handwritten core growth."""
    if category not in CORE_MEGA_CATEGORIES or current <= MEGA_FILE_HARD_LIMIT:
        return None

    path_text = path.as_posix()
    exception = base_exceptions.get(path_text)
    if exception is not None:
        ceiling = exception.get("max_effective_loc")
        if isinstance(ceiling, int) and current <= ceiling:
            return None

    # A legacy file already above the circuit breaker may shrink without first
    # obtaining an exception. Growth remains blocked so the legacy state cannot
    # become a permanently expanding entitlement.
    if previous is not None and previous > MEGA_FILE_HARD_LIMIT and current <= previous:
        return None

    reason = "crossed the 500 eLOC core mega-file circuit breaker"
    if previous is None:
        reason = "introduced a new core file above the 500 eLOC circuit breaker"
    elif previous > MEGA_FILE_HARD_LIMIT:
        reason = "grew a legacy core mega-file beyond its previous size"
    if exception is not None:
        ceiling = exception.get("max_effective_loc")
        reason = f"exceeded the base-approved mega-file ceiling of {ceiling} eLOC"

    return {
        "classification": "INVARIANT_FAILURE",
        "trigger_id": "QR-MEGA-001",
        "scope": {
            "path": path_text,
            "category": category,
            "subject": path.name,
        },
        "facts": [
            {
                "kind": "effective_file_loc",
                "subject": path.name,
                "value": current,
                "tool": "python:tokenize",
                "interpretation": "circuit-breaker-threshold-crossed",
            }
        ],
        "deltas": [
            {
                "kind": "effective_file_loc",
                "before": previous,
                "after": current,
                "delta": None if previous is None else current - previous,
            }
        ],
        "reason": reason,
        "exception_source": "base-ref-only",
        "remediation": (
            "Improve cohesion through a real responsibility boundary, or obtain a separate "
            "architecture exception merged into the branch base before retrying this change."
        ),
    }
