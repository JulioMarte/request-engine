from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tokenize
from pathlib import Path
from typing import Any

TARGET_ROOTS = ("src", "tests")
FILE_LOC_REVIEW_THRESHOLD = 120
MCCABE_REVIEW_THRESHOLD = 10
EVIDENCE_SCHEMA = "quality-evidence/v1"
SEMANTIC_REVIEW_PROTOCOL = "docs/engineering-quality/semantic-review-protocol.md"
AGENT_REVIEW_PLAYBOOK = "docs/engineering-quality/agent-semantic-review-playbook.md"
DEFAULT_OUTPUT = Path(".ci/python-quality-signals.json")
IGNORED_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
}
_C901_SCORE = re.compile(r"\((?P<score>\d+)\s*>\s*(?P<threshold>\d+)\)")
_C901_SUBJECT = re.compile(r"`(?P<subject>[^`]+)`")


def effective_code_lines(source: str) -> int:
    lines: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type in IGNORED_TOKEN_TYPES:
            continue
        lines.update(range(token.start[0], token.end[0] + 1))
    return len(lines)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def changed_python_files(base_ref: str) -> list[Path]:
    result = _git(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base_ref}...HEAD",
        "--",
        *TARGET_ROOTS,
    )
    tracked = {item for item in result.stdout.splitlines() if item.endswith(".py")}
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *TARGET_ROOTS)
    candidates = tracked | {item for item in untracked.stdout.splitlines() if item.endswith(".py")}
    return sorted(Path(item) for item in candidates if Path(item).is_file())


def source_at_ref(base_ref: str, path: Path) -> str | None:
    result = _git("show", f"{base_ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def _sha(ref: str) -> str:
    return _git("rev-parse", ref).stdout.strip()


def _category(path: Path) -> str:
    return "test" if path.parts and path.parts[0] == "tests" else "production"


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


def parse_ruff_c901(diagnostics: list[dict[str, Any]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for diagnostic in diagnostics:
        if diagnostic.get("code") != "C901":
            continue
        message = str(diagnostic.get("message", ""))
        score_match = _C901_SCORE.search(message)
        subject_match = _C901_SUBJECT.search(message)
        path_text = str(diagnostic.get("filename", "<unknown>"))
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
                    "category": "production",
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
    production_paths = [path for path in paths if _category(path) == "production"]
    if not production_paths:
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
        *[path.as_posix() for path in production_paths],
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "ruff produced no diagnostic"
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
    candidates: list[dict[str, object]] = []
    for path in files:
        current = effective_code_lines(path.read_text(encoding="utf-8"))
        previous_source = source_at_ref(base_ref, path)
        previous = effective_code_lines(previous_source) if previous_source is not None else None
        measurements.append(
            {
                "path": path.as_posix(),
                "category": _category(path),
                "effective_file_loc": current,
                "previous_effective_file_loc": previous,
                "delta": None if previous is None else current - previous,
            }
        )
        candidate = _file_loc_candidate(path, current, previous)
        if candidate is not None:
            candidates.append(candidate)
    if include_ruff:
        candidates.extend(run_ruff_c901(files))
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "base_sha": _sha(base_ref),
        "head_sha": _sha("HEAD"),
        "authority": "heuristic-signals-are-non-blocking",
        "thresholds": {
            "effective_file_loc_review_candidate": FILE_LOC_REVIEW_THRESHOLD,
            "mccabe_review_candidate": MCCABE_REVIEW_THRESHOLD,
            "threshold_status": "calibration-trigger-not-quality-invariant",
        },
        "measurements": measurements,
        "candidates": candidates,
        "semantic_review_protocol": SEMANTIC_REVIEW_PROTOCOL,
        "agent_review_playbook": AGENT_REVIEW_PLAYBOOK,
    }


def render_feedback(report: dict[str, object]) -> str:
    raw_candidates = report.get("candidates", [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    if not candidates:
        return (
            "[PASS] Python maintainability signal scan: no review candidates in changed "
            "Python files."
        )
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
            "2. Do NOT split files or extract helpers solely to reduce LOC or C901.",
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
    return "\n".join(lines)


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_summary(report: dict[str, object], feedback: str, output: Path) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    raw_candidates = report.get("candidates", [])
    candidate_count = len(raw_candidates) if isinstance(raw_candidates, list) else 0
    summary = [
        "## Python maintainability signals",
        "",
        f"**Candidates:** {candidate_count}",
        f"**Evidence schema:** `{report.get('schema_version', EVIDENCE_SCHEMA)}`",
        "**Authority:** heuristic signals are non-blocking; HARD invariants remain authoritative.",
        "",
        "```text",
        feedback,
        "```",
        "",
        f"Machine-readable evidence: `{output.as_posix()}`",
        "",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(summary))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit non-blocking Python maintainability evidence for semantic review."
    )
    parser.add_argument("--base-ref", default="HEAD^")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = build_report(args.base_ref)
        write_report(report, args.output)
        feedback = render_feedback(report)
        write_github_summary(report, feedback, args.output)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print("[QUALITY-SENSOR-ERROR] deterministic maintainability scan could not complete.")
        print("This is a tooling failure, not a semantic verdict.")
        print(f"- {exc}")
        return 2
    print(feedback)
    print(f"Evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
