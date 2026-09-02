from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import (  # noqa: E402
    business_module_dependency_snapshot,
    classify_path,
    effective_code_lines,
    generated_reason,
    git,
    navigation_observation,
)

TARGET_ROOTS = ("src", "tests", "scripts", "migrations")
FILE_LOC_REVIEW_THRESHOLD = 120
MCCABE_REVIEW_THRESHOLD = 10
SCAN_SCHEMA = "quality-scan/v1"
SEMANTIC_REVIEW_PROTOCOL = "docs/engineering-quality/semantic-review-protocol.md"
AGENT_REVIEW_PLAYBOOK = "docs/engineering-quality/agent-semantic-review-playbook.md"
DEFAULT_OUTPUT = Path(".ci/python-quality-signals.json")
_C901_SCORE = re.compile(r"\((?P<score>\d+)\s*>\s*(?P<threshold>\d+)\)")
_C901_SUBJECT = re.compile(r"`(?P<subject>[^`]+)`")


def _relative_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        return path
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def changed_python_files(base_ref: str) -> list[Path]:
    result = git(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base_ref}...HEAD",
        "--",
        *TARGET_ROOTS,
    )
    tracked = {item for item in result.stdout.splitlines() if item.endswith(".py")}
    untracked = git("ls-files", "--others", "--exclude-standard", "--", *TARGET_ROOTS)
    candidates = tracked | {item for item in untracked.stdout.splitlines() if item.endswith(".py")}
    files: list[Path] = []
    for item in sorted(candidates):
        path = Path(item)
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if generated_reason(path, source) is None:
            files.append(path)
    return files


def source_at_ref(base_ref: str, path: Path) -> str | None:
    result = git("show", f"{base_ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def _sha(ref: str) -> str:
    return git("rev-parse", ref).stdout.strip()


def _category(path: Path) -> str:
    return classify_path(path) or "python_other"


def _candidate_id(trigger_id: str, path: str, subject: str) -> str:
    raw = f"{trigger_id}|{path}|{subject}".encode()
    return f"QR-{hashlib.sha256(raw).hexdigest()[:12]}"


def _file_loc_candidate(
    path: Path, current: int, previous: int | None
) -> dict[str, object] | None:
    if current <= FILE_LOC_REVIEW_THRESHOLD:
        return None
    path_text = path.as_posix()
    return {
        "candidate_id": _candidate_id("QR-FSIZE-001", path_text, path.name),
        "classification": "REVIEW_CANDIDATE",
        "trigger_id": "QR-FSIZE-001",
        "scope": {"path": path_text, "category": _category(path), "subject": path.name},
        "facts": [
            {
                "kind": "effective_file_loc",
                "subject": path.name,
                "value": current,
                "tool": "python:tokenize",
                "interpretation": "none",
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
        "review_questions": [
            "Does this file contain more than one independently changing responsibility?",
            "Would extraction reduce reasoning cost without adding forwarding/navigation ceremony?",
            "Is the size mostly declarative/linear rather than decision-heavy?",
        ],
    }


def _module_root(path: Path) -> Path | None:
    parts = path.parts
    if len(parts) >= 4 and parts[:3] == ("src", "request_engine", "modules"):
        return Path(*parts[:4])
    return None


def _module_file_count(ref: str, root: Path) -> int:
    result = git("ls-tree", "-r", "--name-only", ref, "--", root.as_posix(), check=False)
    if result.returncode != 0:
        return 0
    return sum(1 for item in result.stdout.splitlines() if item.endswith(".py"))


def _current_module_file_count(root: Path) -> int:
    result = git("ls-files", "--", root.as_posix())
    return sum(1 for item in result.stdout.splitlines() if item.endswith(".py"))


def _navigation_candidate(
    path: Path,
    observation: dict[str, object],
    *,
    is_new: bool,
    base_ref: str,
) -> dict[str, object] | None:
    if not is_new or path.name == "__init__.py":
        return None
    forwarding_only = observation.get("forwarding_only_functions") is True
    reexport_only = observation.get("reexport_only_module") is True
    if not forwarding_only and not reexport_only:
        return None

    facts: list[dict[str, object]] = [
        {
            "kind": "one_call_forwarder_count",
            "subject": path.name,
            "value": int(observation.get("one_call_forwarder_count", 0)),
            "tool": "python:ast",
            "interpretation": "none",
        },
        {
            "kind": "reexport_only_module",
            "subject": path.name,
            "value": reexport_only,
            "tool": "python:ast",
            "interpretation": "none",
        },
    ]
    deltas: list[dict[str, object]] = []
    root = _module_root(path)
    if root is not None:
        before = _module_file_count(base_ref, root)
        after = _current_module_file_count(root)
        facts.append(
            {
                "kind": "module_python_file_count",
                "subject": root.as_posix(),
                "value": after,
                "tool": "git:tracked-files",
                "interpretation": "none",
            }
        )
        deltas.append(
            {
                "kind": "module_python_file_count",
                "before": before,
                "after": after,
                "delta": after - before,
            }
        )

    return {
        "candidate_id": _candidate_id("QR-NAV-001", path.as_posix(), path.name),
        "classification": "REVIEW_CANDIDATE",
        "trigger_id": "QR-NAV-001",
        "scope": {
            "path": path.as_posix(),
            "category": _category(path),
            "subject": path.name,
        },
        "facts": facts,
        "deltas": deltas,
        "review_questions": [
            "Does this new indirection represent a real ownership or substitution boundary?",
            "Does it shorten the reasoning path, or only move one call/re-export to another file?",
            "Would keeping behavior local be easier to navigate without weakening a boundary?",
        ],
    }


def _module_records(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = snapshot.get("modules", [])
    if not isinstance(raw, list):
        return {}
    records: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        module = item.get("module")
        if isinstance(module, str):
            records[module] = item
    return records


def _edge_pairs(snapshot: dict[str, object]) -> set[tuple[str, str]]:
    raw = snapshot.get("edges", [])
    if not isinstance(raw, list):
        return set()
    pairs: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if isinstance(source, str) and isinstance(target, str):
            pairs.add((source, target))
    return pairs


def _coupling_candidates(
    base_snapshot: dict[str, object], current_snapshot: dict[str, object]
) -> list[dict[str, object]]:
    base_records = _module_records(base_snapshot)
    current_records = _module_records(current_snapshot)
    candidates: list[dict[str, object]] = []
    for module, current in sorted(current_records.items()):
        previous = base_records.get(module, {})
        current_outbound = current.get("outbound_modules", [])
        previous_outbound = previous.get("outbound_modules", [])
        current_set = set(current_outbound) if isinstance(current_outbound, list) else set()
        previous_set = set(previous_outbound) if isinstance(previous_outbound, list) else set()
        added = sorted(str(item) for item in current_set - previous_set)
        if not added:
            continue

        fan_out = int(current.get("fan_out", 0))
        previous_fan_out = int(previous.get("fan_out", 0))
        fan_in = int(current.get("fan_in", 0))
        previous_fan_in = int(previous.get("fan_in", 0))
        path = f"src/request_engine/modules/{module}"
        candidates.append(
            {
                "candidate_id": _candidate_id("QR-COUPLING-001", path, module),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-COUPLING-001",
                "scope": {
                    "path": path,
                    "category": "module_coupling",
                    "subject": module,
                },
                "facts": [
                    {
                        "kind": "module_fan_out",
                        "subject": module,
                        "value": fan_out,
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                    {
                        "kind": "module_fan_in",
                        "subject": module,
                        "value": fan_in,
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                    {
                        "kind": "added_outbound_dependency_count",
                        "subject": module,
                        "value": len(added),
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                    {
                        "kind": "added_outbound_modules",
                        "subject": module,
                        "value": ",".join(added),
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                ],
                "deltas": [
                    {
                        "kind": "module_fan_out",
                        "before": previous_fan_out,
                        "after": fan_out,
                        "delta": fan_out - previous_fan_out,
                    },
                    {
                        "kind": "module_fan_in",
                        "before": previous_fan_in,
                        "after": fan_in,
                        "delta": fan_in - previous_fan_in,
                    },
                ],
                "review_questions": [
                    "Does each new synchronous dependency represent a real capability need?",
                    (
                        "Is this module still the correct owner/coordinator for the added "
                        "dependencies?"
                    ),
                    (
                        "Would an event, read model, or existing contract reduce coupling "
                        "without hiding it?"
                    ),
                    (
                        "Would a helper/service-locator merely hide the same dependency "
                        "from the graph?"
                    ),
                ],
            }
        )
    return candidates


def parse_ruff_c901(diagnostics: list[dict[str, Any]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for diagnostic in diagnostics:
        if diagnostic.get("code") != "C901":
            continue
        message = str(diagnostic.get("message", ""))
        score_match = _C901_SCORE.search(message)
        subject_match = _C901_SUBJECT.search(message)
        path = _relative_path(str(diagnostic.get("filename", "<unknown>")))
        subject = subject_match.group("subject") if subject_match else "<function>"
        score = int(score_match.group("score")) if score_match else None
        location = diagnostic.get("location") or {}
        candidates.append(
            {
                "candidate_id": _candidate_id("QR-CPLX-001", path.as_posix(), subject),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-CPLX-001",
                "scope": {
                    "path": path.as_posix(),
                    "category": _category(path),
                    "subject": subject,
                    "line": location.get("row") if isinstance(location, dict) else None,
                },
                "facts": [
                    {
                        "kind": "function_mccabe",
                        "subject": subject,
                        "value": score,
                        "tool": "ruff:C901",
                        "interpretation": "none",
                    }
                ],
                "deltas": [],
                "review_questions": [
                    (
                        "Where does the reasoning load come from: branches, state, "
                        "ordering, or effects?"
                    ),
                    "Can decision structure be simplified without distributing it across helpers?",
                    "Would extraction create a real responsibility boundary and preserve locality?",
                ],
            }
        )
    return candidates


def run_ruff_c901(paths: list[Path]) -> list[dict[str, object]]:
    if not paths:
        return []
    result = subprocess.run(
        [
            "uv",
            "run",
            "ruff",
            "check",
            "--select",
            "C901",
            "--output-format",
            "json",
            "--exit-zero",
            *[path.as_posix() for path in paths],
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Ruff produced no diagnostic"
        raise RuntimeError(f"Ruff C901 sensor failed: {detail}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ruff C901 sensor returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise RuntimeError("Ruff C901 sensor returned an unexpected JSON shape")
    return parse_ruff_c901([item for item in payload if isinstance(item, dict)])


def build_report(base_ref: str, *, include_ruff: bool = True) -> dict[str, object]:
    files = changed_python_files(base_ref)
    measurements: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        current = effective_code_lines(source)
        previous_source = source_at_ref(base_ref, path)
        previous = effective_code_lines(previous_source) if previous_source is not None else None
        category = _category(path)
        measurements.append(
            {
                "path": path.as_posix(),
                "category": category,
                "effective_file_loc": current,
                "previous_effective_file_loc": previous,
                "delta": None if previous is None else current - previous,
            }
        )
        candidate = _file_loc_candidate(path, current, previous)
        if candidate is not None:
            candidates.append(candidate)
        observation = navigation_observation(path, source)
        observation["category"] = category
        observations.append(observation)
        navigation_candidate = _navigation_candidate(
            path,
            observation,
            is_new=previous_source is None,
            base_ref=base_ref,
        )
        if navigation_candidate is not None:
            candidates.append(navigation_candidate)

    base_coupling = business_module_dependency_snapshot(base_ref)
    current_coupling = business_module_dependency_snapshot()
    candidates.extend(_coupling_candidates(base_coupling, current_coupling))

    if include_ruff:
        candidates.extend(run_ruff_c901(files))

    base_edges = _edge_pairs(base_coupling)
    current_edges = _edge_pairs(current_coupling)
    return {
        "schema_version": SCAN_SCHEMA,
        "base_sha": _sha(base_ref),
        "head_sha": _sha("HEAD"),
        "authority": "maintainability-signals-are-non-blocking",
        "thresholds": {
            "effective_file_loc_review_candidate": FILE_LOC_REVIEW_THRESHOLD,
            "mccabe_review_candidate": MCCABE_REVIEW_THRESHOLD,
            "module_coupling": (
                "no numeric threshold; new outbound dependency edges trigger review"
            ),
            "threshold_status": "calibration-triggers-not-architecture-cliffs",
        },
        "measurements": measurements,
        "navigation_observations": observations,
        "module_coupling": {
            "base": base_coupling,
            "current": current_coupling,
            "added_edges": [
                {"source": source, "target": target}
                for source, target in sorted(current_edges - base_edges)
            ],
            "removed_edges": [
                {"source": source, "target": target}
                for source, target in sorted(base_edges - current_edges)
            ],
        },
        "invariant_failures": [],
        "candidates": candidates,
        "semantic_review_protocol": SEMANTIC_REVIEW_PROTOCOL,
        "agent_review_playbook": AGENT_REVIEW_PLAYBOOK,
    }


def _render_candidates(candidates: list[object]) -> list[str]:
    if not candidates:
        return []
    lines = [
        f"[REVIEW_CANDIDATE] {len(candidates)} non-blocking maintainability signal(s) detected.",
        "NON-BLOCKING: these are evidence for semantic review, not defects or invariant failures.",
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        scope = candidate.get("scope") if isinstance(candidate.get("scope"), dict) else {}
        facts = candidate.get("facts") if isinstance(candidate.get("facts"), list) else []
        fact = facts[0] if facts and isinstance(facts[0], dict) else {}
        lines.append(
            f"- {candidate.get('trigger_id')} {scope.get('path')}::{scope.get('subject')} "
            f"{fact.get('kind')}={fact.get('value')}"
        )
    lines.extend(
        [
            "AGENT ACTION:",
            f"1. Read {AGENT_REVIEW_PLAYBOOK} and {SEMANTIC_REVIEW_PROTOCOL}.",
            "2. Do NOT split files, hide dependencies, or extract helpers solely to lower metrics.",
            (
                "3. Review responsibility, complexity, side effects, locality, ownership, "
                "and coupling."
            ),
            (
                "4. Return HEALTHY_AS_IS, REVIEW_CONCERN, REFACTOR_RECOMMENDED, "
                "ARCHITECTURE_CONCERN, or INSUFFICIENT_CONTEXT."
            ),
            "5. If code changes, rerun deterministic architecture and relevant behavior proofs.",
            (
                "Deterministic architecture/correctness invariant failures remain "
                "independently blocking."
            ),
        ]
    )
    return lines


def render_feedback(report: dict[str, object]) -> str:
    raw_candidates = report.get("candidates", [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    lines = _render_candidates(candidates)
    if lines:
        return "\n".join(lines)
    return "[PASS] Python maintainability signal scan: no review candidates detected."


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_summary(report: dict[str, object], feedback: str, output: Path) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    raw_candidates = report.get("candidates", [])
    candidate_count = len(raw_candidates) if isinstance(raw_candidates, list) else 0
    coupling = report.get("module_coupling", {})
    added_edges = coupling.get("added_edges", []) if isinstance(coupling, dict) else []
    edge_count = len(added_edges) if isinstance(added_edges, list) else 0
    summary = [
        "## Python maintainability signals",
        "",
        f"**Candidates:** {candidate_count}",
        "**Invariant failures:** 0",
        f"**New module dependency edges:** {edge_count}",
        f"**Scan schema:** `{report.get('schema_version', SCAN_SCHEMA)}`",
        "**Authority:** heuristic maintainability/coupling signals are non-blocking.",
        "",
        "```text",
        feedback,
        "```",
        "",
        f"Machine-readable scan: `{output.as_posix()}`",
        "",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(summary))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit non-blocking Python maintainability evidence."
    )
    parser.add_argument("--base-ref", default="HEAD^")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = build_report(args.base_ref)
        write_report(report, args.output)
        feedback = render_feedback(report)
        write_github_summary(report, feedback, args.output)
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        SyntaxError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        print("[QUALITY-SENSOR-ERROR] deterministic maintainability scan could not complete.")
        print("This is a tooling failure, not a semantic verdict.")
        print(f"- {exc}")
        return 2
    print(feedback)
    print(f"Scan evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
