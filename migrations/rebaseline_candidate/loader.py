from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
_ROLE_NAME = re.compile(r'^CREATE ROLE "([^"]+)" WITH .+;$')


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported rebaseline candidate manifest")
    return payload


def _verified_file(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_bytes:
        raise RuntimeError(
            f"{path.name}: expected {expected_bytes} bytes, found {len(payload)}"
        )
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise RuntimeError(
            f"{path.name}: expected sha256 {expected_sha256}, found {digest}"
        )
    return payload


def load_schema_sql() -> str:
    manifest = _manifest()["schema_payload"]
    payloads: list[bytes] = []
    for part in manifest["materialized_parts"]:
        payloads.append(
            _verified_file(
                ROOT / part["path"],
                expected_bytes=part["bytes"],
                expected_sha256=part["sha256"],
            )
        )
    payload = b"".join(payloads)
    if len(payload) != manifest["bytes"]:
        raise RuntimeError("materialized schema byte length does not match manifest")
    if _sha256(payload) != manifest["sha256"]:
        raise RuntimeError("materialized schema checksum does not match manifest")
    text = payload.decode("utf-8")
    if any(line.startswith("\\") for line in text.splitlines()):
        raise RuntimeError("rebaseline schema contains a psql meta-command")
    return text


def load_role_statements() -> dict[str, str]:
    manifest = _manifest()["role_bootstrap"]
    payload = _verified_file(
        ROOT / manifest["path"],
        expected_bytes=manifest["bytes"],
        expected_sha256=manifest["sha256"],
    )
    statements: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        statement = line.strip()
        if not statement:
            continue
        match = _ROLE_NAME.fullmatch(statement)
        if match is None:
            raise RuntimeError("rebaseline role bootstrap contains an unexpected statement")
        role_name = match.group(1)
        if role_name in statements:
            raise RuntimeError(f"duplicate rebaseline role statement: {role_name}")
        statements[role_name] = statement
    if len(statements) != _manifest()["effective_model"]["roles"]:
        raise RuntimeError("rebaseline role bootstrap count does not match manifest")
    return statements
