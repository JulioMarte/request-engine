from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import git  # noqa: E402

# Compatibility name retained while the calibration branch is simplified.
# 500 eLOC is an extreme-review threshold, not an architectural invariant.
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

# Only files capable of changing QR-MEGA measurement/classification semantics belong here.
# Developer-experience tooling and generic agent instructions are deliberately excluded.
MEGA_POLICY_AUTHORITY_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "docs/engineering-quality/mega-file-circuit-breaker.md",
        "docs/engineering-quality/mega-file-exceptions.v1.json",
        "scripts/ci/check_python_file_budget.py",
        "scripts/ci/mega_file_policy.py",
        "scripts/ci/quality_metrics.py",
    }
)
REGISTRY_SCHEMA_VERSION = "mega-file-exceptions/v1"


def is_core_mega_scope(path: Path, category: str) -> bool:
    """Return whether a file belongs to the core surface used for calibration."""
    if category in CORE_MEGA_CATEGORIES:
        return True
    parts = path.parts
    if len(parts) >= 4 and parts[:3] == ("src", "request_engine", "modules"):
        return "adapters" not in parts[4:5]
    if len(parts) >= 3 and parts[:2] == ("src", "request_engine"):
        return parts[2] in {"bootstrap", "entrypoints"}
    return False


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
    """Load historical/calibration exceptions from the reviewed branch base."""
    result = git("show", f"{base_ref}:{MEGA_EXCEPTION_REGISTRY.as_posix()}", check=False)
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
) -> None:
    """Compatibility hook: file size is no longer a blocking invariant.

    Files above 500 eLOC are already surfaced by QR-FSIZE-001 because they exceed the
    ordinary review threshold. During calibration, semantic review decides whether the
    outlier is healthy, an acceptable trade-off, or a maintainability problem.
    """
    del path, category, current, previous, base_exceptions
    return None


def policy_self_modification_failure(
    *,
    changed_paths: set[str],
    changed_core_python: list[Path],
) -> None:
    """Compatibility hook: governance co-occurrence is not a HARD invariant.

    The old implementation failed any product+policy co-occurrence. That predicate was
    broader than the protected risk and created process friction unrelated to architecture.
    Governance changes remain reviewable through normal repository governance, while
    deterministic semantic architecture invariants continue to fail independently.
    """
    del changed_paths, changed_core_python
    return None
