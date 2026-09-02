from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import (  # noqa: E402
    business_module_dependency_snapshot,
    classify_path,
    distribution,
    effective_code_lines,
    function_records,
    generated_reason,
    nonblank_text_lines,
    parse_ruff_complexity_payload,
    repository_sha,
    tracked_files,
)

SCHEMA_VERSION = "engineering-quality-baseline/v1"
DEFAULT_OUTPUT = Path(".ci/engineering-quality-baseline.json")
PYTHON_ROOTS = ("src", "tests", "scripts", "migrations")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _relative_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _run_all_function_mccabe() -> list[dict[str, object]]:
    existing_roots = [root for root in PYTHON_ROOTS if Path(root).exists()]
    if not existing_roots:
        return []
    command = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        "C901",
        "--config",
        "lint.mccabe.max-complexity=0",
        "--output-format",
        "json",
        "--exit-zero",
        *existing_roots,
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Ruff produced no diagnostic"
        raise RuntimeError(f"repository-wide Ruff C901 baseline failed: {detail}")
    try:
        payload: Any = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("repository-wide Ruff C901 baseline returned invalid JSON") from exc
    records = parse_ruff_complexity_payload(payload)
    for record in records:
        record["path"] = _relative_path(str(record["path"]))
    return records


def _top_records(
    records: list[dict[str, object]], value_key: str, *, limit: int = 20
) -> list[dict[str, object]]:
    usable = [item for item in records if isinstance(item.get(value_key), int)]
    return sorted(usable, key=lambda item: int(item[value_key]), reverse=True)[:limit]


def build_baseline() -> dict[str, object]:
    files: list[dict[str, object]] = []
    functions: list[dict[str, object]] = []
    generated: list[dict[str, str]] = []

    for path in tracked_files():
        category = classify_path(path)
        if category is None:
            continue
        source = _read_text(path)
        if source is None:
            continue
        reason = generated_reason(path, source)
        if reason is not None:
            generated.append({"path": path.as_posix(), "reason": reason})
            continue
        if path.suffix == ".py":
            file_record: dict[str, object] = {
                "path": path.as_posix(),
                "category": category,
                "metric": "effective_file_loc",
                "value": effective_code_lines(source),
            }
            files.append(file_record)
            for record in function_records(path, source):
                record["category"] = category
                functions.append(record)
        elif category == "config":
            files.append(
                {
                    "path": path.as_posix(),
                    "category": category,
                    "metric": "nonblank_text_loc",
                    "value": nonblank_text_lines(source),
                }
            )

    mccabe = _run_all_function_mccabe()
    categories_by_path = {str(item["path"]): str(item["category"]) for item in files}
    for record in mccabe:
        record["category"] = categories_by_path.get(str(record["path"]), "python_other")

    by_category: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for record in files:
        value = record.get("value")
        if isinstance(value, int):
            by_category[str(record["category"])][str(record["metric"])].append(value)
    for record in functions:
        value = record.get("function_loc")
        if isinstance(value, int):
            by_category[str(record["category"])]["function_loc"].append(value)
    for record in mccabe:
        value = record.get("mccabe")
        if isinstance(value, int):
            by_category[str(record["category"])]["function_mccabe"].append(value)

    categories: dict[str, object] = {}
    for category, metrics in sorted(by_category.items()):
        categories[category] = {
            metric: distribution(values) for metric, values in sorted(metrics.items())
        }

    coupling = business_module_dependency_snapshot()
    raw_modules = coupling.get("modules", [])
    coupling_modules = [item for item in raw_modules if isinstance(item, dict)]
    fan_in_values = [
        int(item["fan_in"]) for item in coupling_modules if isinstance(item.get("fan_in"), int)
    ]
    fan_out_values = [
        int(item["fan_out"])
        for item in coupling_modules
        if isinstance(item.get("fan_out"), int)
    ]
    coupling_summary = {
        "edge_count": len(coupling.get("edges", []))
        if isinstance(coupling.get("edges"), list)
        else 0,
        "distributions": {
            "fan_in": distribution(fan_in_values),
            "fan_out": distribution(fan_out_values),
        },
        "modules": coupling_modules,
        "edges": coupling.get("edges", []),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "repository_sha": repository_sha(),
        "methodology": {
            "percentile_method": "nearest-rank",
            "python_file_loc": "tokenize effective code-bearing lines",
            "function_loc": "AST physical span from lineno through end_lineno",
            "function_mccabe": "Ruff C901 with calibration threshold forced to 0",
            "config_loc": "nonblank text lines; no Python threshold is applied",
            "module_coupling": (
                "AST direct imports between src/request_engine/modules business modules; "
                "fan-out counts distinct outbound modules and fan-in distinct inbound modules"
            ),
            "generated_policy": (
                "controlled generated paths and generated filename conventions are excluded; "
                "source comments are not generated-code authority"
            ),
        },
        "categories": categories,
        "module_coupling": coupling_summary,
        "records": {
            "files": files,
            "functions": functions,
            "mccabe": mccabe,
        },
        "outliers": {
            "file_loc": _top_records(files, "value"),
            "function_loc": _top_records(functions, "function_loc"),
            "function_mccabe": _top_records(mccabe, "mccabe"),
            "module_fan_in": _top_records(coupling_modules, "fan_in"),
            "module_fan_out": _top_records(coupling_modules, "fan_out"),
        },
        "generated_exclusions": generated,
    }


def render_summary(baseline: dict[str, object]) -> str:
    categories = baseline.get("categories")
    if not isinstance(categories, dict):
        return "No category distributions were produced."
    lines = [
        "## Repository engineering-quality baseline",
        "",
        f"Repository SHA: `{baseline.get('repository_sha')}`",
        "Percentiles use the deterministic nearest-rank method.",
        "",
        "| Category | Metric | Count | p50 | p75 | p90 | p95 | p99 | Max |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, raw_metrics in sorted(categories.items()):
        if not isinstance(raw_metrics, dict):
            continue
        for metric, raw_distribution in sorted(raw_metrics.items()):
            if not isinstance(raw_distribution, dict):
                continue
            values = raw_distribution
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(category),
                        str(metric),
                        str(values.get("count")),
                        str(values.get("p50")),
                        str(values.get("p75")),
                        str(values.get("p90")),
                        str(values.get("p95")),
                        str(values.get("p99")),
                        str(values.get("max")),
                    ]
                )
                + " |"
            )

    coupling = baseline.get("module_coupling")
    if isinstance(coupling, dict):
        modules = coupling.get("modules")
        if isinstance(modules, list):
            lines.extend(
                [
                    "",
                    "## Business-module coupling",
                    "",
                    f"Direct cross-module import edges: **{coupling.get('edge_count', 0)}**",
                    "",
                    "| Module | Fan-in | Fan-out | Inbound | Outbound |",
                    "|---|---:|---:|---|---|",
                ]
            )
            for raw in modules:
                if not isinstance(raw, dict):
                    continue
                inbound = raw.get("inbound_modules", [])
                outbound = raw.get("outbound_modules", [])
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(raw.get("module")),
                            str(raw.get("fan_in")),
                            str(raw.get("fan_out")),
                            ", ".join(str(item) for item in inbound)
                            if isinstance(inbound, list)
                            else "",
                            ", ".join(str(item) for item in outbound)
                            if isinstance(outbound, list)
                            else "",
                        ]
                    )
                    + " |"
                )
    return "\n".join(lines)


def _write_github_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(text + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        baseline = build_baseline()
    except (OSError, RuntimeError, subprocess.SubprocessError, SyntaxError, ValueError) as exc:
        print(f"[QUALITY-BASELINE-ERROR] {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = render_summary(baseline)
    print(summary)
    _write_github_summary(summary)
    print(f"Baseline evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
