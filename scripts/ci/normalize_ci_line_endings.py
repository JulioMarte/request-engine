#!/usr/bin/env python3
"""Normalize Bash scripts to LF for Windows-mounted local CI worktrees."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    changed: list[Path] = []
    for path in sorted(ROOT.rglob("*.sh")):
        if ".git" in path.parts or ".local-ci" in path.parts:
            continue
        data = path.read_bytes()
        normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalized == data:
            continue
        path.write_bytes(normalized)
        changed.append(path.relative_to(ROOT))

    if changed:
        print(f"Normalized {len(changed)} shell script(s) to LF.")
        for path in changed:
            print(f"- {path}")
    else:
        print("Shell scripts already use LF line endings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
