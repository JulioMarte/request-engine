from __future__ import annotations

import argparse
import json
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
GUARANTEES = ROOT / "docs/testing/current-guarantees.toml"
PROOF_MAP = ROOT / "docs/testing/current-proof-map.toml"


def _toml(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], tomllib.loads(path.read_text(encoding="utf-8")))


def _test_path(classname: str) -> str | None:
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = Path(*parts[:end]).with_suffix(".py")
        exists = candidate.parts and candidate.parts[0] == "tests" and (ROOT / candidate).is_file()
        if exists:
            return candidate.as_posix()
    return None


def _executed_paths(junit_dir: Path) -> set[str]:
    executed: set[str] = set()
    for report in sorted(junit_dir.glob("*.xml")):
        for case in ET.parse(report).getroot().iter("testcase"):
            classname = case.attrib.get("classname")
            if classname and (path := _test_path(classname)):
                executed.add(path)
    return executed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prove current invariants from tests executed by the PostgreSQL gate"
    )
    parser.add_argument("--junit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    guarantees = _toml(GUARANTEES)["guarantees"]
    proofs = _toml(PROOF_MAP)["proofs"]
    executed = _executed_paths(args.junit_dir)
    evidence: dict[str, set[str]] = defaultdict(set)
    executed_proofs: dict[str, list[str]] = defaultdict(list)

    for proof in proofs:
        path = cast(str, proof["path"])
        if path not in executed:
            continue
        identifier = cast(str, proof["guarantee"])
        evidence[identifier].update(cast(list[str], proof["evidence"]))
        executed_proofs[identifier].append(path)

    gaps: list[dict[str, object]] = []
    for guarantee in guarantees:
        identifier = cast(str, guarantee["id"])
        if not identifier.startswith("INV-"):
            continue
        required = set(cast(list[str], guarantee["required_evidence"]))
        missing = sorted(required - evidence[identifier])
        if missing:
            gaps.append({"guarantee": identifier, "missing_evidence": missing})

    payload = {
        "schema_version": 1,
        "executed_test_files": len(executed),
        "executed_mapped_proofs": dict(sorted(executed_proofs.items())),
        "gaps": gaps,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.output.write_text(serialized, encoding="utf-8")
    if gaps:
        gap_descriptions = [f"{gap['guarantee']}={gap['missing_evidence']}" for gap in gaps]
        details = ", ".join(gap_descriptions)
        raise SystemExit(f"current-product proof execution gaps: {details}")


if __name__ == "__main__":
    main()
