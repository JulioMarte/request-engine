from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

DEFAULT_SCHEMA = Path("docs/engineering-quality/schemas/quality-evidence-v2.schema.json")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_version(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "selected quality-evidence schema"
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return "selected quality-evidence schema"
    version_property = properties.get("schema_version")
    if not isinstance(version_property, dict):
        return "selected quality-evidence schema"
    version = version_property.get("const")
    return version if isinstance(version, str) and version else "selected quality-evidence schema"


def validate_packets(schema_path: Path, packet_dir: Path) -> list[str]:
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    failures: list[str] = []
    packet_paths = sorted(packet_dir.glob("QR-*.json"))
    if not packet_paths:
        return []
    for path in packet_paths:
        payload = _load_json(path)
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
        for error in errors:
            location = ".".join(str(item) for item in error.path) or "<root>"
            failures.append(f"{path.as_posix()}:{location}: {error.message}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--packet-dir", type=Path, default=Path(".ci/quality-evidence"))
    args = parser.parse_args()
    try:
        schema = _load_json(args.schema)
        version = schema_version(schema)
        failures = validate_packets(args.schema, args.packet_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[QUALITY-EVIDENCE-SCHEMA-ERROR] {exc}")
        return 2
    if failures:
        print(f"[QUALITY-EVIDENCE-INVALID] generated packet(s) do not satisfy {version}")
        for failure in failures:
            print(f"- {failure}")
        print(
            "AGENT ACTION: fix packet generation or evolve the versioned schema explicitly; "
            "do not bypass validation."
        )
        return 1
    print(f"[PASS] {version} packets satisfy JSON Schema Draft 2020-12.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
