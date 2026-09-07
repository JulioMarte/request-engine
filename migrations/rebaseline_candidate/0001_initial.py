"""Proposed pre-production Request Engine initial baseline.

This revision is deliberately outside migrations/versions until its exact
materialized schema payload has passed the single-Alembic fresh-cluster proof.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from alembic import op
from psycopg import ClientCursor, sql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CANDIDATE_DIR_ENV = "REQUEST_ENGINE_REBASELINE_CANDIDATE_DIR"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate_dir() -> Path:
    override = os.environ.get(_CANDIDATE_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent


def _manifest(candidate_dir: Path) -> dict[str, Any]:
    path = candidate_dir / "manifest.json"
    manifest = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if manifest.get("schema_version") != 1:
        raise RuntimeError(f"unsupported rebaseline candidate manifest: {path}")
    return manifest


def load_candidate_sql(candidate_dir: Path | None = None) -> str:
    root = candidate_dir or _candidate_dir()
    manifest = _manifest(root)
    schema = cast(dict[str, Any], manifest["schema_payload"])
    payload_parts: list[bytes] = []

    for part in cast(list[dict[str, Any]], schema["materialized_parts"]):
        path = root / cast(str, part["path"])
        payload = path.read_bytes()
        expected_bytes = cast(int, part["bytes"])
        expected_sha256 = cast(str, part["sha256"])
        if len(payload) != expected_bytes:
            raise RuntimeError(
                f"{path}: expected {expected_bytes} bytes, found {len(payload)}"
            )
        digest = _sha256(payload)
        if digest != expected_sha256:
            raise RuntimeError(
                f"{path}: expected sha256 {expected_sha256}, found {digest}"
            )
        payload_parts.append(payload)

    payload = b"".join(payload_parts)
    expected_bytes = cast(int, schema["bytes"])
    expected_sha256 = cast(str, schema["sha256"])
    if len(payload) != expected_bytes:
        raise RuntimeError(
            f"reconstructed baseline expected {expected_bytes} bytes, found {len(payload)}"
        )
    digest = _sha256(payload)
    if digest != expected_sha256:
        raise RuntimeError(
            f"reconstructed baseline expected sha256 {expected_sha256}, found {digest}"
        )

    text = payload.decode("utf-8")
    meta_commands = [line for line in text.splitlines() if line.startswith("\\")]
    if meta_commands:
        raise RuntimeError(
            f"rebaseline candidate contains psql meta-command(s): {meta_commands}"
        )
    return text


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("Request Engine initial baseline requires Alembic online mode")
    bind = op.get_bind()
    if bind is None:
        raise RuntimeError("Request Engine initial baseline requires a live database connection")

    driver_connection = bind.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("Request Engine initial baseline requires the psycopg driver connection")

    with ClientCursor(driver_connection) as cursor:
        cursor.execute(sql.SQL(load_candidate_sql()))

    bind.exec_driver_sql("RESET ALL")


def downgrade() -> None:
    raise RuntimeError("Request Engine initial baseline is irreversible")
