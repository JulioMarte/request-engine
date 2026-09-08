from uuid import uuid4

import psycopg
import pytest

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


def test_workload_credential_is_only_readable_through_auth_boundary(admin_conn) -> None:
    authority_id = uuid4()
    identity_id = uuid4()
    credential_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            id, kind, issuer_or_environment
        ) VALUES (%s, 'workload', %s)
        """,
        (authority_id, f"workload-test-{uuid4().hex}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.workload_identities (
            id, identity_authority_id, workload_kind
        ) VALUES (%s, %s, 'agent')
        """,
        (identity_id, authority_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.workload_credentials (
            id, workload_identity_id, token_digest, token_fingerprint, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '1 hour')
        """,
        (credential_id, identity_id, b"w" * 32, "ab" * 8),
    )

    admin_conn.execute("SET ROLE request_engine_app")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin_conn.execute("SELECT * FROM request_engine.workload_credentials").fetchall()
        row = admin_conn.execute(
            "SELECT * FROM request_auth.read_workload_credential(%s)",
            (credential_id,),
        ).fetchone()
    finally:
        admin_conn.execute("RESET ROLE")

    assert row is not None
    assert row[0] == credential_id
    assert row[1] == identity_id
    assert row[2] == authority_id
    assert row[3] == "agent"
    assert bytes(row[4]) == b"w" * 32


def test_workload_identity_rejects_non_workload_authority(admin_conn) -> None:
    authority_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            id, kind, issuer_or_environment
        ) VALUES (%s, 'native', %s)
        """,
        (authority_id, f"not-workload-{uuid4().hex}"),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.workload_identities (
                identity_authority_id, workload_kind
            ) VALUES (%s, 'agent')
            """,
            (authority_id,),
        )
