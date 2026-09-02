from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mega_file_policy import MEGA_POLICY_AUTHORITY_PATHS, is_core_mega_scope  # noqa: E402
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


def render_review(policy_paths: list[str], core_paths: list[str]) -> str:
    return "\n".join(
        [
            "[GOVERNANCE_REVIEW] QR-MEGA-GOV-001",
            "WHAT: this change edits core product Python and quality-policy authority together.",
            f"POLICY PATHS: {policy_paths}",
            f"CORE PYTHON: {core_paths}",
            (
                "INTERPRETATION: co-occurrence is not itself an architecture violation. Review "
                "whether the policy change can materially alter a verdict from which the product "
                "change benefits."
            ),
            (
                "ACTION: if the relationship is causal/self-authorizing, separate or independently "
                "review the governance change. If unrelated, no forced PR split is required."
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
        description="Surface product/policy co-occurrence for causal governance review."
    )
    parser.add_argument("--base-ref", default="HEAD^")
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base_ref)
        core = changed_core_python(paths)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[QUALITY-POLICY-SEPARATION-ERROR] {exc}")
        return 2

    policy_paths = sorted(paths & MEGA_POLICY_AUTHORITY_PATHS)
    core_paths = sorted(path.as_posix() for path in core)
    if policy_paths and core_paths:
        message = render_review(policy_paths, core_paths)
    else:
        message = (
            "[PASS] quality-policy separation: no product/policy co-occurrence requiring "
            f"governance review. policy_changes={policy_paths}"
        )
    print(message)
    _write_summary(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
