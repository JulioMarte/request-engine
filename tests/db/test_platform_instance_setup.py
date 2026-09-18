"""Platform Instance and SetupSession persistence guarantees (ADR 0014, P1).

These proofs protect the durable trust-root data model before any claim HTTP
surface exists:

- the Instance is a structural singleton whose lifecycle is independent of users;
- claim is one-way and its identity columns are immutable;
- SetupSessions are digest-only, bounded, and fail closed once the Instance is
  claimed, with the active-session cap serialized against concurrent creation.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
]

_DIGEST = bytes(range(32))
_FINGERPRINT = "0123456789abcdef"


def _insert_instance(
    admin_conn: PgConnection,
    *,
    state: str = "unclaimed",
) -> tuple[UUID, UUID]:
    native = uuid4()
    workload = uuid4()
    if state == "claimed":
        admin_conn.execute(
            """
            INSERT INTO request_engine.platform_instance (
                singleton_key, id, state, built_in_native_authority_id,
                built_in_workload_authority_id, claimed_at,
                initial_owner_principal_id, claim_provenance
            ) VALUES (
                1, %s, 'claimed', %s, %s, clock_timestamp(), %s, 'test_adoption'
            )
            """,
            (uuid4(), native, workload, uuid4()),
        )
    else:
        admin_conn.execute(
            """
            INSERT INTO request_engine.platform_instance (
                singleton_key, id, state, built_in_native_authority_id,
                built_in_workload_authority_id
            ) VALUES (1, %s, 'unclaimed', %s, %s)
            """,
            (uuid4(), native, workload),
        )
    return native, workload


def _insert_pending_session(
    admin_conn: PgConnection,
    *,
    digest: bytes,
    fingerprint: str,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> UUID:
    now = datetime.now(UTC)
    session_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.setup_sessions (
            id, instance_id, token_digest, token_fingerprint, mode,
            created_at, expires_at
        )
        SELECT %s, instance.id, %s, %s, 'interactive', %s, %s
          FROM request_engine.platform_instance AS instance
         WHERE instance.singleton_key = 1
        """,
        (
            session_id,
            digest,
            fingerprint,
            created_at or now,
            expires_at or (now + timedelta(minutes=20)),
        ),
    )
    return session_id


def test_platform_instance_is_a_structural_singleton(admin_conn: PgConnection) -> None:
    _insert_instance(admin_conn)

    with pytest.raises(Error) as second_key:
        admin_conn.execute(
            """
            INSERT INTO request_engine.platform_instance (
                singleton_key, id, state, built_in_native_authority_id,
                built_in_workload_authority_id
            ) VALUES (2, %s, 'unclaimed', %s, %s)
            """,
            (uuid4(), uuid4(), uuid4()),
        )
    assert second_key.value.sqlstate == "23514"

    with pytest.raises(Error) as duplicate:
        _insert_instance(admin_conn)
    assert duplicate.value.sqlstate == "23505"


def test_platform_instance_claim_shape_is_enforced(admin_conn: PgConnection) -> None:
    with pytest.raises(Error) as claimed_without_owner:
        admin_conn.execute(
            """
            INSERT INTO request_engine.platform_instance (
                singleton_key, id, state, built_in_native_authority_id,
                built_in_workload_authority_id, claimed_at
            ) VALUES (1, %s, 'claimed', %s, %s, clock_timestamp())
            """,
            (uuid4(), uuid4(), uuid4()),
        )
    assert claimed_without_owner.value.sqlstate == "23514"


def test_platform_instance_claim_transition_is_one_way_and_immutable(
    admin_conn: PgConnection,
) -> None:
    _insert_instance(admin_conn)
    admin_conn.execute(
        """
        UPDATE request_engine.platform_instance
           SET state = 'claimed',
               revision = revision + 1,
               claimed_at = clock_timestamp(),
               initial_owner_principal_id = %s,
               claim_provenance = 'installation_claim'
         WHERE singleton_key = 1
        """,
        (uuid4(),),
    )

    with pytest.raises(Error) as reopen:
        admin_conn.execute(
            """
            UPDATE request_engine.platform_instance
               SET state = 'unclaimed',
                   revision = revision + 1,
                   claimed_at = NULL,
                   initial_owner_principal_id = NULL,
                   claim_provenance = NULL
             WHERE singleton_key = 1
            """
        )
    assert reopen.value.sqlstate == "55000"

    with pytest.raises(Error) as identity_change:
        admin_conn.execute(
            "UPDATE request_engine.platform_instance "
            "SET built_in_native_authority_id = %s WHERE singleton_key = 1",
            (uuid4(),),
        )
    assert identity_change.value.sqlstate == "55000"

    with pytest.raises(Error) as silent_revision:
        admin_conn.execute(
            "UPDATE request_engine.platform_instance "
            "SET revision = revision + 5 WHERE singleton_key = 1"
        )
    assert silent_revision.value.sqlstate == "55000"

    with pytest.raises(Error) as undeletable:
        admin_conn.execute("DELETE FROM request_engine.platform_instance WHERE singleton_key = 1")
    assert undeletable.value.sqlstate == "55000"


def test_setup_session_creation_is_digest_only_and_bounded(
    admin_conn: PgConnection,
) -> None:
    _insert_instance(admin_conn)
    admin_conn.execute("SET ROLE request_platform_control")
    try:
        created = admin_conn.execute(
            "SELECT request_platform.create_setup_session(%s, %s, %s, 'interactive', 1200)",
            (uuid4(), _DIGEST, _FINGERPRINT),
        ).fetchone()
        assert created is not None

        with pytest.raises(Error) as bad_digest:
            admin_conn.execute(
                "SELECT request_platform.create_setup_session(%s, %s, %s, 'interactive', 1200)",
                (uuid4(), b"short", _FINGERPRINT),
            )
        assert bad_digest.value.sqlstate == "22023"

        with pytest.raises(Error) as bad_mode:
            admin_conn.execute(
                "SELECT request_platform.create_setup_session(%s, %s, %s, 'nope', 1200)",
                (uuid4(), bytes(range(31, 63)), _FINGERPRINT),
            )
        assert bad_mode.value.sqlstate == "22023"

        with pytest.raises(Error) as bad_ttl:
            admin_conn.execute(
                "SELECT request_platform.create_setup_session(%s, %s, %s, 'interactive', 5)",
                (uuid4(), bytes(range(64, 96)), _FINGERPRINT),
            )
        assert bad_ttl.value.sqlstate == "22023"
    finally:
        admin_conn.execute("RESET ROLE")

    stored = admin_conn.execute(
        "SELECT token_digest, token_fingerprint, status, mode FROM request_engine.setup_sessions"
    ).fetchall()
    assert len(stored) == 1
    assert bytes(stored[0][0]) == _DIGEST
    assert stored[0][1] == _FINGERPRINT
    assert stored[0][2] == "pending"
    assert stored[0][3] == "interactive"

    columns = {
        str(row[0])
        for row in admin_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'request_engine' AND table_name = 'setup_sessions'"
        ).fetchall()
    }
    assert columns.isdisjoint({"token", "raw_token", "secret", "plaintext"})


@pytest.mark.concurrency
@pytest.mark.adversarial
def test_setup_session_active_cap_is_race_safe(
    pg_conninfo: str,
    admin_conn: PgConnection,
) -> None:
    _insert_instance(admin_conn)
    workers = 8
    barrier = threading.Barrier(workers)
    digests = [bytes([index]) * 32 for index in range(workers)]
    fingerprints = [f"{index:016x}" for index in range(workers)]

    def attempt(index: int) -> str:
        conn = psycopg.connect(pg_conninfo, autocommit=True)
        try:
            conn.execute("SET ROLE request_platform_control")
            barrier.wait(timeout=15)
            try:
                conn.execute(
                    "SELECT request_platform.create_setup_session(%s, %s, %s, 'automated', 600)",
                    (uuid4(), digests[index], fingerprints[index]),
                )
                return "created"
            except Error as exc:
                return f"rejected:{exc.sqlstate}"
            finally:
                conn.execute("RESET ROLE")
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(attempt, range(workers)))

    assert results.count("created") == 5
    assert sorted(result for result in results if result != "created") == ["rejected:54000"] * 3
    assert admin_conn.execute("SELECT count(*) FROM request_engine.setup_sessions").fetchone() == (
        5,
    )


def test_setup_session_creation_fails_closed_after_claim(
    admin_conn: PgConnection,
) -> None:
    _insert_instance(admin_conn, state="claimed")
    admin_conn.execute("SET ROLE request_platform_control")
    try:
        with pytest.raises(Error) as closed:
            admin_conn.execute(
                "SELECT request_platform.create_setup_session(%s, %s, %s, 'interactive', 600)",
                (uuid4(), _DIGEST, _FINGERPRINT),
            )
        assert closed.value.sqlstate == "55000"
    finally:
        admin_conn.execute("RESET ROLE")
    assert admin_conn.execute("SELECT count(*) FROM request_engine.setup_sessions").fetchone() == (
        0,
    )


def test_read_setup_session_is_usable_only_while_live_and_unclaimed(
    admin_conn: PgConnection,
) -> None:
    _insert_instance(admin_conn)
    _insert_pending_session(admin_conn, digest=_DIGEST, fingerprint=_FINGERPRINT)
    expired_digest = bytes([9]) * 32
    expired_at = datetime.now(UTC)
    _insert_pending_session(
        admin_conn,
        digest=expired_digest,
        fingerprint="0000000000000009",
        created_at=expired_at - timedelta(minutes=2),
        expires_at=expired_at - timedelta(minutes=1),
    )

    admin_conn.execute("SET ROLE request_platform_control")
    try:
        live = admin_conn.execute(
            "SELECT is_usable, instance_state FROM request_platform.read_setup_session(%s)",
            (_DIGEST,),
        ).fetchone()
        assert live == (True, "unclaimed")

        expired = admin_conn.execute(
            "SELECT is_usable, instance_state FROM request_platform.read_setup_session(%s)",
            (expired_digest,),
        ).fetchone()
        assert expired == (False, "unclaimed")

        unknown = admin_conn.execute(
            "SELECT count(*) FROM request_platform.read_setup_session(%s)",
            (bytes([7]) * 32,),
        ).fetchone()
        assert unknown == (0,)
    finally:
        admin_conn.execute("RESET ROLE")

    admin_conn.execute(
        """
        UPDATE request_engine.platform_instance
           SET state = 'claimed', revision = revision + 1,
               claimed_at = clock_timestamp(),
               initial_owner_principal_id = %s,
               claim_provenance = 'installation_claim'
         WHERE singleton_key = 1
        """,
        (uuid4(),),
    )
    admin_conn.execute("SET ROLE request_platform_control")
    try:
        after_claim = admin_conn.execute(
            "SELECT is_usable, instance_state FROM request_platform.read_setup_session(%s)",
            (_DIGEST,),
        ).fetchone()
        assert after_claim == (False, "claimed")
    finally:
        admin_conn.execute("RESET ROLE")


def test_setup_session_transitions_are_guarded(admin_conn: PgConnection) -> None:
    _insert_instance(admin_conn)
    session_id = _insert_pending_session(admin_conn, digest=_DIGEST, fingerprint=_FINGERPRINT)

    with pytest.raises(Error) as silent_revision:
        admin_conn.execute(
            "UPDATE request_engine.setup_sessions SET revision = revision + 1 WHERE id = %s",
            (session_id,),
        )
    assert silent_revision.value.sqlstate == "55000"

    with pytest.raises(Error) as delete_pending:
        admin_conn.execute("DELETE FROM request_engine.setup_sessions WHERE id = %s", (session_id,))
    assert delete_pending.value.sqlstate == "55000"

    admin_conn.execute(
        "UPDATE request_engine.setup_sessions "
        "SET status = 'consumed', revision = revision + 1, consumed_at = clock_timestamp() "
        "WHERE id = %s",
        (session_id,),
    )
    with pytest.raises(Error) as terminal:
        admin_conn.execute(
            "UPDATE request_engine.setup_sessions "
            "SET status = 'revoked', revision = revision + 1, revoked_at = clock_timestamp() "
            "WHERE id = %s",
            (session_id,),
        )
    assert terminal.value.sqlstate == "55000"


def test_setup_surface_is_not_reachable_by_application_roles(
    admin_conn: PgConnection,
) -> None:
    for function in (
        "request_platform.create_setup_session(uuid, bytea, text, text, integer)",
        "request_platform.read_setup_session(bytea)",
        "request_platform.read_platform_instance()",
    ):
        assert admin_conn.execute(
            "SELECT has_function_privilege('request_platform_control', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (True,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('request_engine_app', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('public', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)

    for table in ("request_engine.setup_sessions", "request_engine.platform_instance"):
        assert admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'SELECT')", (table,)
        ).fetchone() == (False,)
