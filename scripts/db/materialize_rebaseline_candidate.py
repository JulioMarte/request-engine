from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "migrations" / "rebaseline_candidate" / "manifest.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_verified(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_bytes:
        raise RuntimeError(
            f"{path}: expected {expected_bytes} bytes, found {len(payload)}"
        )
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise RuntimeError(
            f"{path}: expected sha256 {expected_sha256}, found {digest}"
        )
    return payload


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError(f"unsupported rebaseline candidate manifest: {path}")
    return manifest


def materialize(*, artifact_dir: Path, output_dir: Path, manifest_path: Path) -> None:
    manifest = _load_manifest(manifest_path)
    schema = manifest["schema_payload"]
    roles = manifest["role_bootstrap"]

    schema_payload = _read_verified(
        artifact_dir / schema["source_artifact_name"],
        expected_bytes=schema["bytes"],
        expected_sha256=schema["sha256"],
    )
    role_payload = _read_verified(
        artifact_dir / roles["source_artifact_name"],
        expected_bytes=roles["bytes"],
        expected_sha256=roles["sha256"],
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    offset = 0
    for part in schema["materialized_parts"]:
        size = part["bytes"]
        payload = schema_payload[offset : offset + size]
        if len(payload) != size or _sha256(payload) != part["sha256"]:
            raise RuntimeError(
                f"schema candidate split no longer matches manifest at {part['path']}"
            )
        (output_dir / part["path"]).write_bytes(payload)
        offset += size

    if offset != len(schema_payload):
        raise RuntimeError(
            f"manifest covers {offset} schema bytes, payload has {len(schema_payload)}"
        )

    role_output = output_dir / roles["path"]
    role_output.write_bytes(role_payload)
    if _sha256(role_output.read_bytes()) != roles["sha256"]:
        raise RuntimeError("materialized role bootstrap failed checksum verification")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the exact audited Request Engine rebaseline candidate."
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "migrations" / "rebaseline_candidate",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    materialize(
        artifact_dir=args.artifact_dir,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
    )


if __name__ == "__main__":
    main()
