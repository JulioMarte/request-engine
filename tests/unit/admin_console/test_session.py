import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from request_engine.entrypoints.http.admin_console.session import (
    AdminSession,
    FileSessionStore,
    session_expiry,
)


def test_opaque_session_survives_worker_restart_and_revokes(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    secret = b"test-session-encryption-secret-32-bytes"
    first = FileSessionStore(directory, secret)
    session = AdminSession("private-upstream-bearer", "csrf", int(time.time()) + 600)
    handle = first.create(session, "login")
    assert len(handle) == 43
    assert session.access_token not in handle
    assert session.access_token.encode() not in next(directory.iterdir()).read_bytes()
    second = FileSessionStore(directory, secret)
    assert second.read(handle, "login") == session
    assert second.read(handle, "setup") is None
    assert second.read("../" + handle, "login") is None
    second.revoke(handle, "login")
    assert first.read(handle, "login") is None


def test_expired_tampered_and_wrong_key_sessions_fail_closed(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    store = FileSessionStore(directory, b"first-secret")
    expired = store.create(AdminSession("bearer", "csrf", int(time.time()) - 1), "setup")
    assert store.read(expired, "setup") is None
    valid = store.create(AdminSession("bearer", "csrf", int(time.time()) + 600), "login")
    assert FileSessionStore(directory, b"other-secret").read(valid, "login") is None
    assert store.read(valid[:-1] + ("A" if valid[-1] != "A" else "B"), "login") is None


def test_local_session_cannot_outlive_reported_upstream_expiry() -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=20)
    assert session_expiry(600, deadline.isoformat()) == int(deadline.timestamp())
    assert session_expiry(600, "not-a-timestamp") == 0
