from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove only PostgreSQL plain-dump psql guard directives"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()

    kept: list[str] = []
    for line in args.source.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("\\restrict ") or line.startswith("\\unrestrict "):
            continue
        if line.startswith("\\"):
            raise SystemExit(
                f"unexpected psql meta-command in pg_dump output: {line.rstrip()!r}"
            )
        kept.append(line)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text("".join(kept), encoding="utf-8")


if __name__ == "__main__":
    main()
