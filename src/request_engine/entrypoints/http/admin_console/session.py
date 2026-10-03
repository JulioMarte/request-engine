"""Opaque sessions in a private persistent BFF credential store.

Records are immutable: reads cannot renew or resurrect a revoked session.
Replicas must share the same volume and encryption secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from secrets import token_urlsafe
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken

from request_engine.entrypoints.http.admin_console.json_types import as_mapping

_HANDLE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
SessionKind = Literal["login", "setup"]


@dataclass(frozen=True)
class AdminSession:
    """Server-held upstream credential and local CSRF/expiry boundary."""

    access_token: str
    csrf_token: str
    expires_at: int


def new_csrf_token() -> str:
    return token_urlsafe(32)


def session_expiry(ttl_seconds: int, upstream_expiry: object = None) -> int:
    """Never outlive a supplied upstream expiry; do not decode opaque bearers."""
    local = int(time.time()) + ttl_seconds
    if upstream_expiry is None:
        return local
    if not isinstance(upstream_expiry, str):
        return 0
    try:
        parsed = datetime.fromisoformat(upstream_expiry.replace("Z", "+00:00"))
        return min(local, int(parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp()))
    except ValueError:
        return 0


class FileSessionStore:
    """Encrypted, cross-worker persistent records on a private shared volume.

    Only random 256-bit handles reach browsers. File names hash those handles;
    authenticated encryption binds the record to its handle and session kind.
    Exclusive creation prevents overwrite; logout deletes the immutable record.
    Storage failures propagate, never fall back to cookie credential payloads.
    """

    def __init__(self, directory: Path, secret: bytes) -> None:
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("session store must be a private directory, not a symlink")
        if os.name != "nt" and directory.stat().st_mode & 0o077:
            raise ValueError("session store directory must deny group/other access (0700)")
        key = hashlib.sha256(b"request-engine-admin-session-v1\x00" + secret).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(key))

    def _path(self, handle: str, kind: SessionKind) -> Path | None:
        if not _HANDLE.fullmatch(handle):
            return None
        digest = hashlib.sha256(handle.encode("ascii")).hexdigest()
        return self.directory / f"{kind}-{digest}.session"

    def create(self, session: AdminSession, kind: SessionKind) -> str:
        self.prune()
        handle = token_urlsafe(32)
        path = self._path(handle, kind)
        assert path is not None
        payload = {**asdict(session), "handle": handle, "kind": kind}
        encrypted = self._cipher.encrypt(json.dumps(payload).encode())
        # Nothing references this record until its complete durable write returns.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        return handle

    def read(self, handle: str, kind: SessionKind) -> AdminSession | None:
        path = self._path(handle, kind)
        if path is None or path.is_symlink():
            return None
        try:
            payload = as_mapping(json.loads(self._cipher.decrypt(path.read_bytes())))
        except (FileNotFoundError, InvalidToken, ValueError):
            return None
        if payload.get("handle") != handle or payload.get("kind") != kind:
            return None
        token, csrf, expiry = (
            payload.get("access_token"),
            payload.get("csrf_token"),
            payload.get("expires_at"),
        )
        if not isinstance(token, str) or not isinstance(csrf, str):
            return None
        if not isinstance(expiry, int) or isinstance(expiry, bool):
            return None
        if expiry <= time.time():
            path.unlink(missing_ok=True)
            return None
        return AdminSession(token, csrf, expiry)

    def revoke(self, handle: str, kind: SessionKind) -> None:
        path = self._path(handle, kind)
        if path is not None:
            path.unlink(missing_ok=True)

    def prune(self, *, limit: int = 64) -> None:
        """Bound cleanup work per login; never scan an unbounded session directory."""
        cutoff = time.time() - 43200
        with os.scandir(self.directory) as entries:
            for entry in islice(entries, limit):
                try:
                    if entry.name.endswith(".session") and entry.stat().st_mtime < cutoff:
                        Path(entry.path).unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
