from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import (  # noqa: E402
    business_module_dependency_snapshot,
    generated_reason,
    git,
    navigation_observation,
    repository_sha,
    suppression_observation,
)

SCHEMA_VERSION = "architecture-diff/v1"
DEFAULT_OUTPUT = Path(".ci/architecture-diff.json")
PYTHON_ROOTS = ("src", "tests", "scripts", "migrations")


def _source_at_ref(ref: str, path: Path) -> str | None:
    result = git("show", f"{ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def _changed_python_paths(base_ref: str) -> list[Path]:
    result = git(
        "diff",
        "--name-only",
        "--diff-filter=ACMRD",
        f"{base_ref}...HEAD",
        "--",
        *PYTHON_ROOTS,
    )
    return sorted({Path(item) for item in result.stdout.splitlines() if item.endswith(".py")})


def _edge_records(snapshot: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    raw = snapshot.get("edges", [])
    if not isinstance(raw, list):
        return {}
    records: dict[tuple[str, str], dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if isinstance(source, str) and isinstance(target, str):
            records[(source, target)] = item
    return records


def _symbols(record: dict[str, object] | None) -> set[str]:
    if record is None:
        return set()
    raw = record.get("contract_symbols", [])
    return {str(item) for item in raw} if isinstance(raw, list) else set()


def _coupling_diff(base: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    base_records = _edge_records(base)
    current_records = _edge_records(current)
    base_edges = set(base_records)
    current_edges = set(current_records)

    contract_deltas: list[dict[str, object]] = []
    for edge in sorted(base_edges | current_edges):
        before = _symbols(base_records.get(edge))
        after = _symbols(current_records.get(edge))
        added = sorted(after - before)
        removed = sorted(before - after)
        if not added and not removed:
            continue
        contract_deltas.append(
            {
                "source": edge[0],
                "target": edge[1],
                "before_symbol_count": len(before),
                "after_symbol_count": len(after),
                "added_contract_symbols": added,
                "removed_contract_symbols": removed,
                "interpretation": "none",
            }
        )

    return {
        "added_edges": [
            {"source": source, "target": target}
            for source, target in sorted(current_edges - base_edges)
        ],
        "removed_edges": [
            {"source": source, "target": target}
            for source, target in sorted(base_edges - current_edges)
        ],
        "contract_usage_deltas": contract_deltas,
    }


def _suppression_diff(base_ref: str, paths: list[Path]) -> dict[str, object]:
    files: list[dict[str, object]] = []
    total_before = 0
    total_after = 0
    for path in paths:
        before_source = _source_at_ref(base_ref, path)
        after_source = path.read_text(encoding="utf-8") if path.is_file() else None
        if after_source is not None and generated_reason(path, after_source) is not None:
            continue
        if (
            after_source is None
            and before_source is not None
            and generated_reason(path, before_source) is not None
        ):
            continue

        before = suppression_observation(before_source or "")
        after = suppression_observation(after_source or "")
        before_total = int(before.get("total", 0))
        after_total = int(after.get("total", 0))
        total_before += before_total
        total_after += after_total
        if before_total == after_total and before.get("counts") == after.get("counts"):
            continue
        files.append(
            {
                "path": path.as_posix(),
                "before": before,
                "after": after,
                "delta": after_total - before_total,
                "interpretation": "none",
            }
        )
    return {
        "scope": "changed-python-files",
        "before": total_before,
        "after": total_after,
        "delta": total_after - total_before,
        "files": files,
        "markers": ["noqa", "type: ignore", "nosec", "pragma: no cover"],
        "interpretation": "none",
    }


def _navigation_diff(base_ref: str, paths: list[Path]) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for path in paths:
        before_source = _source_at_ref(base_ref, path)
        after_source = path.read_text(encoding="utf-8") if path.is_file() else None
        if before_source is None and after_source is None:
            continue
        try:
            before = (
                navigation_observation(path, before_source)
                if before_source is not None
                else {
                    "function_count": 0,
                    "one_call_forwarder_count": 0,
                    "forwarding_only_functions": False,
                    "reexport_only_module": False,
                }
            )
            after = (
                navigation_observation(path, after_source)
                if after_source is not None
                else {
                    "function_count": 0,
                    "one_call_forwarder_count": 0,
                    "forwarding_only_functions": False,
                    "reexport_only_module": False,
                }
            )
        except SyntaxError:
            # The canonical lint/type/architecture jobs own syntax failure. This
            # evidence builder must not invent a navigability verdict from an
            # unparsable intermediate file.
            continue

        before_forwarders = int(before.get("one_call_forwarder_count", 0))
        after_forwarders = int(after.get("one_call_forwarder_count", 0))
        before_reexport = before.get("reexport_only_module") is True
        after_reexport = after.get("reexport_only_module") is True
        if before_forwarders == after_forwarders and before_reexport == after_reexport:
            continue
        changes.append(
            {
                "path": path.as_posix(),
                "one_call_forwarder_count": {
                    "before": before_forwarders,
                    "after": after_forwarders,
                    "delta": after_forwarders - before_forwarders,
                },
                "reexport_only_module": {
                    "before": before_reexport,
                    "after": after_reexport,
                },
                "interpretation": "none",
            }
        )
    return changes


def _provenance(base_ref: str) -> dict[str, str]:
    tested_sha = repository_sha()
    source_head_sha = os.environ.get("QUALITY_SOURCE_HEAD_SHA", tested_sha)
    base_sha = repository_sha(base_ref)
    test_mode = os.environ.get("QUALITY_TEST_MODE", "BRANCH_HEAD")
    return {
        "base_sha": base_sha,
        "source_head_sha": source_head_sha,
        "tested_sha": tested_sha,
        "test_mode": test_mode,
    }


def build_architecture_diff(base_ref: str) -> dict[str, object]:
    paths = _changed_python_paths(base_ref)
    base_coupling = business_module_dependency_snapshot(base_ref)
    current_coupling = business_module_dependency_snapshot()
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "informational-review-evidence",
        "provenance": _provenance(base_ref),
        "module_coupling": _coupling_diff(base_coupling, current_coupling),
        "suppressions": _suppression_diff(base_ref, paths),
        "navigation": _navigation_diff(base_ref, paths),
        "review_contract": {
            "no_synthetic_score": True,
            "no_numeric_coupling_cliff": True,
            "new_edges_require_context": True,
            "contract_growth_is_evidence_not_defect": True,
            "suppression_growth_is_evidence_not_defect": True,
        },
    }


def render_summary(payload: dict[str, object]) -> str:
    coupling = payload.get("module_coupling", {})
    suppressions = payload.get("suppressions", {})
    navigation = payload.get("navigation", [])
    provenance = payload.get("provenance", {})
    if not isinstance(coupling, dict):
        coupling = {}
    if not isinstance(suppressions, dict):
        suppressions = {}
    if isinstance(provenance, dict):
        test_mode = provenance.get("test_mode")
        source_head_sha = provenance.get("source_head_sha")
        tested_sha = provenance.get("tested_sha")
    else:
        test_mode = None
        source_head_sha = None
        tested_sha = None
    navigation_count = len(navigation) if isinstance(navigation, list) else 0
    lines = [
        "## Architecture diff",
        "",
        f"Test mode: `{test_mode}`",
        f"Source head: `{source_head_sha}`",
        f"Tested tree: `{tested_sha}`",
        "",
        f"Added module edges: **{len(coupling.get('added_edges', []))}**",
        f"Removed module edges: **{len(coupling.get('removed_edges', []))}**",
        f"Contract-usage deltas: **{len(coupling.get('contract_usage_deltas', []))}**",
        f"Suppression delta on changed Python: **{suppressions.get('delta', 0):+}**",
        f"Navigation-shape deltas: **{navigation_count}**",
        "",
        (
            "No architecture score is computed. These deltas provide review context; "
            "HARD invariants remain independent."
        ),
    ]
    return "\n".join(lines)


def _write_github_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(text + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="HEAD^")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        payload = build_architecture_diff(args.base_ref)
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        print(f"[ARCHITECTURE-DIFF-ERROR] evidence collection failed: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = render_summary(payload)
    print(summary)
    _write_github_summary(summary)
    print(f"Architecture diff evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
