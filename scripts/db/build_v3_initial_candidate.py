from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLY_SCRIPT = ROOT / "scripts/db/apply_v3_candidate.sh"
CANDIDATE_DIR = ROOT / "migrations/sql/v3_candidate"


def ordered_candidate_files() -> list[Path]:
    source = APPLY_SCRIPT.read_text(encoding="utf-8")
    names = re.findall(r'^\s*"(\d{3}-[^"]+\.sql)"\s*$', source, flags=re.MULTILINE)
    if not names:
        raise SystemExit("could not discover candidate migration order")
    files = [CANDIDATE_DIR / name for name in names]
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise SystemExit(f"candidate migration files are missing: {', '.join(missing)}")
    return files


def render_initial() -> str:
    sections = [
        "-- GENERATED RELEASE-CANDIDATE ARTIFACT. DO NOT EDIT BY HAND.",
        "-- Source of truth remains migrations/sql/v3_candidate until release gates pass.",
        "",
    ]
    for path in ordered_candidate_files():
        sections.extend(
            (
                f"-- BEGIN SOURCE: {path.name}",
                path.read_text(encoding="utf-8").rstrip(),
                f"-- END SOURCE: {path.name}",
                "",
            )
        )
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_initial(), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
