from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Require two generated proof files to be byte-identical")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected_hash = _sha256(args.expected)
    actual_hash = _sha256(args.actual)
    equivalent = (
        args.expected.stat().st_size == args.actual.stat().st_size
        and expected_hash == actual_hash
        and args.expected.read_bytes() == args.actual.read_bytes()
    )
    result = {
        "equivalent": equivalent,
        "expected_bytes": args.expected.stat().st_size,
        "actual_bytes": args.actual.stat().st_size,
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not equivalent:
        raise SystemExit("generated proof files are not byte-identical")


if __name__ == "__main__":
    main()
