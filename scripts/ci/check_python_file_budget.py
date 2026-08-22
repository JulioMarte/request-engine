from __future__ import annotations

import argparse
import io
import subprocess
import tokenize
from pathlib import Path

TARGET_ROOTS = ("src", "tests")
SOFT_TARGET = 100
HARD_MAX = 120
ADOPTION_BASELINE = "900b4e227e435ef88bfb9d20155e355e44a8a633"
IGNORED_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
}


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


def effective_base_ref(base_ref: str) -> str:
    adopted = _git("merge-base", "--is-ancestor", ADOPTION_BASELINE, base_ref, check=False)
    return base_ref if adopted.returncode == 0 else ADOPTION_BASELINE


def changed_python_files(base_ref: str) -> list[Path]:
    result = _git(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base_ref}...HEAD",
        "--",
        *TARGET_ROOTS,
    )
    return [Path(item) for item in result.stdout.splitlines() if item.endswith(".py")]


def source_at_ref(base_ref: str, path: Path) -> str | None:
    result = _git("show", f"{base_ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def violation(path: Path, current: int, previous: int | None) -> str | None:
    if current <= HARD_MAX:
        return None
    if previous is None or previous <= HARD_MAX:
        return f"{path}: {current} effective lines exceeds hard max {HARD_MAX}"
    if current > previous:
        return (
            f"{path}: legacy oversized file grew {previous} -> {current} effective lines; "
            "files above the hard max may not grow"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="HEAD^")
    args = parser.parse_args()
    base_ref = effective_base_ref(args.base_ref)

    failures: list[str] = []
    for path in changed_python_files(base_ref):
        if not path.is_file():
            continue
        current = effective_code_lines(path.read_text(encoding="utf-8"))
        previous_source = source_at_ref(base_ref, path)
        previous = effective_code_lines(previous_source) if previous_source is not None else None
        error = violation(path, current, previous)
        if error:
            failures.append(error)
        elif SOFT_TARGET < current <= HARD_MAX:
            print(f"[WARN] {path}: {current} effective lines (target <= {SOFT_TARGET})")

    if failures:
        print("Python file budget violations:")
        for item in failures:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
