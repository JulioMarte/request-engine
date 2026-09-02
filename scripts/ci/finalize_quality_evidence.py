from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_SCAN = Path(".ci/python-quality-signals.json")
DEFAULT_BASELINE = Path(".ci/engineering-quality-baseline.json")
DEFAULT_ARCHITECTURE_DIFF = Path(".ci/architecture-diff.json")
DEFAULT_SUMMARY = Path(".ci/python-quality.json")
DEFAULT_OUTPUT = Path(".ci/quality-evidence")
SCHEMA_VERSION = "quality-evidence/v2"

FITNESS_IDS = {
    "file-budget": "FF-SIGNAL-SCAN-001",
    "quality-baseline": "FF-QUALITY-BASELINE-001",
    "ruff-lint": "FF-PYTHON-LINT-001",
    "ruff-format": "FF-PYTHON-FORMAT-001",
    "pyright": "FF-PYTHON-TYPE-001",
    "architecture": "FF-ARCHITECTURE-SUITE-001",
    "unit": "FF-UNIT-SUITE-001",
    "modules": "FF-MODULE-SUITE-001",
}
STATUS_MAP = {
    "PASS": "pass",
    "FAIL": "fail",
    "SKIP": "skip",
    "TIMEOUT": "timeout",
}


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _tool_version(command: list[str], fallback: str) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except OSError:
        return fallback
    if result.returncode != 0:
        return fallback
    return (result.stdout or result.stderr).strip() or fallback


def _module_for_path(path_text: str) -> str | None:
    parts = Path(path_text).parts
    if len(parts) >= 4 and parts[:3] == ("src", "request_engine", "modules"):
        return parts[3]
    return None


def _context_manifest(scope: dict[str, Any]) -> list[str]:
    path_text = str(scope.get("path", ""))
    items = [
        path_text,
        "AGENTS.md",
        "docs/engineering-quality/agent-semantic-review-playbook.md",
        "docs/engineering-quality/semantic-review-protocol.md",
        "docs/engineering-quality/engineering-quality-architecture-constitution.md",
        "docs/testing/repository-governance-contract.md",
        ".ci/architecture-diff.json",
    ]
    module = _module_for_path(path_text)
    if module is not None:
        readme = Path("src/request_engine/modules") / module / "README.md"
        if readme.is_file():
            items.append(readme.as_posix())
    return list(dict.fromkeys(item for item in items if item))


def _architecture_results(
    summary: dict[str, Any], baseline: dict[str, Any], architecture_diff: dict[str, Any]
) -> list[dict[str, object]]:
    raw_steps = summary.get("steps", [])
    steps = raw_steps if isinstance(raw_steps, list) else []
    results: list[dict[str, object]] = [
        {
            "fitness_id": "FF-QUALITY-BASELINE-001",
            "status": "pass",
            "source": "engineering-quality-baseline",
            "details": str(baseline.get("repository_sha", "")),
        },
        {
            "fitness_id": "FF-ARCH-DIFF-001",
            "status": "pass",
            "source": "architecture-diff",
            "details": str(architecture_diff.get("schema_version", "")),
        },
    ]
    seen: set[str] = {"quality-baseline"}
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key", ""))
        fitness_id = FITNESS_IDS.get(key)
        if fitness_id is None:
            continue
        seen.add(key)
        status = STATUS_MAP.get(str(raw.get("status")), "not_run")
        log = raw.get("log")
        results.append(
            {
                "fitness_id": fitness_id,
                "status": status,
                "source": f"python-quality:{key}",
                "details": str(log) if log else None,
            }
        )
    for key, fitness_id in FITNESS_IDS.items():
        if key in seen:
            continue
        results.append(
            {
                "fitness_id": fitness_id,
                "status": "not_run",
                "source": f"python-quality:{key}",
                "details": None,
            }
        )
    return results


def _candidate_trigger_ids(candidate: dict[str, Any]) -> list[str]:
    trigger_ids = candidate.get("trigger_ids")
    if isinstance(trigger_ids, list) and trigger_ids:
        return sorted({str(item) for item in trigger_ids})
    trigger_id = candidate.get("trigger_id")
    return [str(trigger_id)] if trigger_id else []


def _verified_provenance(
    scan: dict[str, Any], baseline: dict[str, Any], architecture_diff: dict[str, Any]
) -> dict[str, str]:
    raw = architecture_diff.get("provenance")
    if not isinstance(raw, dict):
        raise ValueError("architecture diff is missing provenance")
    base_sha = str(raw.get("base_sha", ""))
    source_head_sha = str(raw.get("source_head_sha", ""))
    tested_sha = str(raw.get("tested_sha", ""))
    test_mode = str(raw.get("test_mode", ""))
    if scan.get("base_sha") != base_sha:
        raise ValueError("scan base SHA does not match architecture-diff provenance")
    if scan.get("head_sha") != tested_sha:
        raise ValueError("scan tested tree does not match architecture-diff provenance")
    if baseline.get("repository_sha") != tested_sha:
        raise ValueError("baseline tree does not match architecture-diff tested tree")
    if test_mode not in {"PR_INTEGRATION_CANDIDATE", "BRANCH_HEAD"}:
        raise ValueError(f"unsupported test_mode={test_mode!r}")
    return {
        "base_sha": base_sha,
        "source_head_sha": source_head_sha,
        "tested_sha": tested_sha,
        "test_mode": test_mode,
    }


def build_packets(
    scan: dict[str, Any],
    baseline: dict[str, Any],
    summary: dict[str, Any],
    architecture_diff: dict[str, Any],
) -> list[dict[str, object]]:
    provenance = _verified_provenance(scan, baseline, architecture_diff)
    architecture_results = _architecture_results(summary, baseline, architecture_diff)
    raw_candidates = scan.get("candidates", [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    tools = {
        "python": platform.python_version(),
        "ruff": _tool_version(["uv", "run", "ruff", "--version"], "unknown"),
    }
    packets: list[dict[str, object]] = []
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            continue
        scope = raw_candidate.get("scope")
        if not isinstance(scope, dict):
            continue
        packet = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": str(raw_candidate.get("candidate_id", "")),
            "classification": "REVIEW_CANDIDATE",
            "trigger_ids": _candidate_trigger_ids(raw_candidate),
            "repository": os.environ.get("GITHUB_REPOSITORY", "JulioMarte/request-engine"),
            "base_sha": provenance["base_sha"],
            "source_head_sha": provenance["source_head_sha"],
            "tested_sha": provenance["tested_sha"],
            "test_mode": provenance["test_mode"],
            "scope": {
                "path": str(scope.get("path", "")),
                "category": str(scope.get("category", "")),
                "subject": str(scope.get("subject", "")),
                "line": scope.get("line") if isinstance(scope.get("line"), int) else None,
                "module": _module_for_path(str(scope.get("path", ""))),
            },
            "facts": raw_candidate.get("facts", []),
            "deltas": raw_candidate.get("deltas", []),
            "architecture_results": architecture_results,
            "context_manifest": _context_manifest(scope),
            "review_questions": raw_candidate.get("review_questions", []),
            "provenance": {
                "scan_schema": str(scan.get("schema_version", "")),
                "baseline_schema": str(baseline.get("schema_version", "")),
                "baseline_sha": str(baseline.get("repository_sha", "")),
                "architecture_diff_schema": str(architecture_diff.get("schema_version", "")),
                "tools": tools,
            },
            "authority": "heuristic-signals-are-non-blocking",
        }
        packets.append(packet)
    return packets


def write_packets(packets: list[dict[str, object]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("QR-*.json"):
        stale.unlink()
    names: list[str] = []
    for packet in packets:
        candidate_id = str(packet["candidate_id"])
        target = output_dir / f"{candidate_id}.json"
        target.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        names.append(target.name)
    index = {
        "schema_version": "quality-evidence-index/v2",
        "packet_schema": SCHEMA_VERSION,
        "count": len(names),
        "packets": names,
    }
    (output_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--architecture-diff", type=Path, default=DEFAULT_ARCHITECTURE_DIFF)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    required = (args.scan, args.baseline, args.architecture_diff, args.summary)
    missing = [path for path in required if not path.is_file()]
    if missing:
        print("[QUALITY-EVIDENCE-FINALIZE-ERROR] required evidence input is missing")
        for path in missing:
            print(f"- {path}")
        return 2
    try:
        scan = _load_object(args.scan)
        baseline = _load_object(args.baseline)
        architecture_diff = _load_object(args.architecture_diff)
        summary = _load_object(args.summary)
        packets = build_packets(scan, baseline, summary, architecture_diff)
        write_packets(packets, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[QUALITY-EVIDENCE-FINALIZE-ERROR] {exc}")
        return 2
    print(f"[PASS] finalized {len(packets)} {SCHEMA_VERSION} packet(s).")
    print(f"Evidence index: {args.output_dir / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
