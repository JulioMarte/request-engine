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

from mega_file_policy import (  # noqa: E402
    CORE_MEGA_CATEGORIES,
    MEGA_EXCEPTION_REGISTRY,
    MEGA_FILE_HARD_LIMIT,
    load_base_exceptions,
    mega_file_failure,
)
from quality_metrics import (  # noqa: E402
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


def _file_loc_candidate(path: Path, current: int, previous: int | None) -> dict[str, object] | None:
    if current <= FILE_LOC_REVIEW_THRESHOLD:
        return None
    path_text = path.as_posix()
    delta = None if previous is None else current - previous
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
                "delta": delta,
            }
        ],
        "review_questions": [
            "Does this file contain more than one independently changing responsibility?",
            (
                "Would extraction reduce reasoning cost without adding forwarding or "
                "navigation ceremony?"
            ),
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
            "Would keeping the behavior local be easier to navigate without weakening a boundary?",
        ],
    }


def parse_ruff_c901(diagnostics: list[dict[str, Any]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for diagnostic in diagnostics:
        if diagnostic.get("code") != "C901":
            continue
        message = str(diagnostic.get("message", ""))
        score_match = _C901_SCORE.search(message)
        subject_match = _C901_SUBJECT.search(message)
        path = _relative_path(str(diagnostic.get("filename", "<unknown>")))
        path_text = path.as_posix()
        subject = subject_match.group("subject") if subject_match else "<function>"
        score = int(score_match.group("score")) if score_match else None
        location = diagnostic.get("location") or {}
        candidates.append(
            {
                "candidate_id": _candidate_id("QR-CPLX-001", path_text, subject),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-CPLX-001",
                "scope": {
                    "path": path_text,
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
                        "Where does the real reasoning load come from: branches, state, "
                        "ordering, or side effects?"
                    ),
                    (
                        "Can decision structure be simplified without merely distributing "
                        "it across helpers?"
                    ),
                    (
                        "Would a proposed extraction create a real responsibility boundary "
                        "and preserve locality?"
                    ),
                ],
            }
        )
    return candidates


def run_ruff_c901(paths: list[Path]) -> list[dict[str, object]]:
    if not paths:
        return []
    command = [
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
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
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
    base_exceptions = load_base_exceptions(base_ref)
    measurements: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    invariant_failures: list[dict[str, object]] = []
    generated_exclusions: list[dict[str, str]] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        reason = generated_reason(path, source)
        if reason is not None:
            generated_exclusions.append({"path": path.as_posix(), "reason": reason})
            continue
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
        failure = mega_file_failure(
            path,
            category=category,
            current=current,
            previous=previous,
            base_exceptions=base_exceptions,
        )
        if failure is not None:
            invariant_failures.append(failure)
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
    if include_ruff:
        candidates.extend(run_ruff_c901(files))
    return {
        "schema_version": SCAN_SCHEMA,
        "base_sha": _sha(base_ref),
        "head_sha": _sha("HEAD"),
        "authority": (
            "heuristic-signals-are-non-blocking; QR-MEGA-001-core-circuit-breaker-is-blocking"
        ),
        "thresholds": {
            "effective_file_loc_review_candidate": FILE_LOC_REVIEW_THRESHOLD,
            "mccabe_review_candidate": MCCABE_REVIEW_THRESHOLD,
            "core_mega_file_hard_limit": MEGA_FILE_HARD_LIMIT,
            "threshold_status": (
                "120-and-C901-are-calibration-triggers; "
                "500-is-a-core-extreme-outlier-circuit-breaker"
            ),
        },
        "mega_file_policy": {
            "core_categories": sorted(CORE_MEGA_CATEGORIES),
            "exception_registry": MEGA_EXCEPTION_REGISTRY.as_posix(),
            "exception_authority": "base-ref-only",
            "base_exception_count": len(base_exceptions),
        },
        "measurements": measurements,
        "navigation_observations": observations,
        "generated_exclusions": generated_exclusions,
        "invariant_failures": invariant_failures,
        "candidates": candidates,
        "semantic_review_protocol": SEMANTIC_REVIEW_PROTOCOL,
        "agent_review_playbook": AGENT_REVIEW_PLAYBOOK,
    }


def _render_invariant_failures(failures: list[object]) -> list[str]:
    if not failures:
        return []
    lines = [
        f"[INVARIANT_FAILURE] {len(failures)} QR-MEGA-001 failure(s).",
        (
            "BLOCKING: handwritten core product Python may not cross or grow beyond "
            f"{MEGA_FILE_HARD_LIMIT} effective LOC without a base-approved exception."
        ),
    ]
    for raw_failure in failures:
        if not isinstance(raw_failure, dict):
            continue
        scope = raw_failure.get("scope") if isinstance(raw_failure.get("scope"), dict) else {}
        facts = raw_failure.get("facts") if isinstance(raw_failure.get("facts"), list) else []
        fact = facts[0] if facts and isinstance(facts[0], dict) else {}
        lines.append(
            f"- QR-MEGA-001 {scope.get('path')} effective_file_loc={fact.get('value')}: "
            f"{raw_failure.get('reason')}"
        )
    lines.extend(
        [
            (
                "SELF-JUSTIFICATION IS INVALID: the author/agent cannot waive QR-MEGA-001 "
                "with rationale, HEALTHY_AS_IS, PR text, comments, or an exception added or "
                "modified in this same change."
            ),
            (
                "VALID OPTIONS: improve the design through a real cohesive responsibility "
                "boundary, or stop and obtain a separate architecture exception merged into "
                "the branch base before retrying the implementation."
            ),
        ]
    )
    return lines


def _render_candidates(candidates: list[object]) -> list[str]:
    if not candidates:
        return []
    candidate_summary = f"[REVIEW_CANDIDATE] {len(candidates)} "
    candidate_summary += "non-blocking maintainability signal(s) detected."
    lines = [
        candidate_summary,
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
            "2. Do NOT split files or extract helpers solely to reduce LOC, C901, or file count.",
            (
                "3. Review responsibility, real reasoning complexity, side effects, locality, "
                "ownership, testability, and metric gaming."
            ),
            (
                "4. Return a semantic disposition: HEALTHY_AS_IS, REVIEW_CONCERN, "
                "REFACTOR_RECOMMENDED, ARCHITECTURE_CONCERN, or INSUFFICIENT_CONTEXT."
            ),
            (
                "5. If code changes, rerun deterministic architecture, lint/type, and relevant "
                "behavior proofs before claiming success."
            ),
            "A deterministic INVARIANT_FAILURE cannot be overridden by semantic review.",
        ]
    )
    return lines


def render_feedback(report: dict[str, object]) -> str:
    raw_failures = report.get("invariant_failures", [])
    failures = raw_failures if isinstance(raw_failures, list) else []
    raw_candidates = report.get("candidates", [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    lines = _render_invariant_failures(failures)
    if lines and candidates:
        lines.append("")
    lines.extend(_render_candidates(candidates))
    if lines:
        return "\n".join(lines)
    return (
        "[PASS] Python maintainability signal scan: no review candidates or invariant "
        "failures in changed handwritten Python files."
    )


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_summary(report: dict[str, object], feedback: str, output: Path) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    raw_candidates = report.get("candidates", [])
    candidate_count = len(raw_candidates) if isinstance(raw_candidates, list) else 0
    raw_failures = report.get("invariant_failures", [])
    failure_count = len(raw_failures) if isinstance(raw_failures, list) else 0
    summary = [
        "## Python maintainability signals",
        "",
        f"**Candidates:** {candidate_count}",
        f"**Invariant failures:** {failure_count}",
        f"**Scan schema:** `{report.get('schema_version', SCAN_SCHEMA)}`",
        (
            "**Authority:** heuristic signals are non-blocking; QR-MEGA-001 and other HARD "
            "invariants remain authoritative."
        ),
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
        description="Emit Python maintainability evidence and enforce precise circuit breakers."
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
        ValueError,
    ) as exc:
        print("[QUALITY-SENSOR-ERROR] deterministic maintainability scan could not complete.")
        print("This is a tooling failure, not a semantic verdict.")
        print(f"- {exc}")
        return 2
    print(feedback)
    print(f"Scan evidence: {args.output}")
    failures = report.get("invariant_failures", [])
    return 1 if isinstance(failures, list) and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
