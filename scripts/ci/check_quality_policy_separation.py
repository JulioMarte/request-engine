from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mega_file_policy import (  # noqa: E402
    MEGA_POLICY_AUTHORITY_PATHS,
    is_core_mega_scope,
    policy_self_modification_failure,
)
from quality_metrics import classify_path, generated_reason, git  # noqa: E402


def changed_paths(base_ref: str) -> set[str]:
    result = git("diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD")
    return {item for item in result.stdout.splitlines() if item}


def changed_core_python(paths: set[str]) -> list[Path]:
    core: list[Path] = []
    for path_text in sorted(paths):
        path = Path(path_text)
        if path.suffix != ".py" or not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if generated_reason(path, source) is not None:
            continue
        category = classify_path(path) or "python_other"
        if is_core_mega_scope(path, category):
            core.append(path)
    return core


def render_failure(failure: dict[str, object]) -> str:
    facts = failure.get("facts")
    fact_list = facts if isinstance(facts, list) else []
    policy_paths: object = []
    core_paths: object = []
    for fact in fact_list:
        if not isinstance(fact, dict):
            continue
        if fact.get("kind") == "policy_authority_paths_changed":
            policy_paths = fact.get("value", [])
        elif fact.get("kind") == "core_python_paths_changed":
            core_paths = fact.get("value", [])
    return "\n".join(
        [
            "[INVARIANT_FAILURE] QR-MEGA-GOV-001",
            "WHAT: this change edits core product Python and the policy authority that judges it.",
            f"POLICY PATHS: {policy_paths}",
            f"CORE PYTHON: {core_paths}",
            (
                "RISK: an author or coding agent could weaken the circuit breaker, generated "
                "exclusion, or CI path while introducing the code that benefits from it."
            ),
            (
                "INVALID: changing the threshold/checker/workflow/exception authority in the "
                "same product implementation, even with a persuasive rationale."
            ),
            (
                "REMEDIATION: split the governance change into a separate reviewed PR, merge "
                "it into development, rebuild/rebase the product branch, then run exact-head CI."
            ),
        ]
    )


def _write_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write("## Quality-policy separation\n\n```text\n")
        handle.write(text)
        handle.write("\n```\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prevent a product change from editing the quality policy that judges it."
    )
    parser.add_argument("--base-ref", default="HEAD^")
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base_ref)
        core = changed_core_python(paths)
        failure = policy_self_modification_failure(
            changed_paths=paths,
            changed_core_python=core,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[QUALITY-POLICY-SEPARATION-ERROR] {exc}")
        return 2
    if failure is None:
        policy_changes = sorted(paths & MEGA_POLICY_AUTHORITY_PATHS)
        message = (
            "[PASS] quality-policy separation: no product change is modifying its own "
            f"mega-file authority. policy_changes={policy_changes}"
        )
        print(message)
        _write_summary(message)
        return 0
    message = render_failure(failure)
    print(message)
    _write_summary(message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
