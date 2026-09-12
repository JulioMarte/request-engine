from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _intent(conn: PgConnection) -> UUID:
    intent_id = uuid4()
    conn.execute(
        """
        INSERT INTO request_engine.platform_bootstrap_intents (
            id, token_digest, token_fingerprint, provenance_reference, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '15 minutes')
        """,
        (intent_id, bytes(range(32)), "0123456789abcdef", f"deployment:{uuid4().hex}"),
    )
    return intent_id


def _tenant_principal(conn: PgConnection) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    org_row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"bootstrap-proof-{suffix}", f"Bootstrap Proof {suffix}"),
    ).fetchone()
    assert org_row is not None
    organization_id = cast(UUID, org_row[0])
    principal_row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s) RETURNING id
        """,
        (organization_id, f"tenant-{uuid4().hex}"),
    ).fetchone()
    assert principal_row is not None
    return organization_id, cast(UUID, principal_row[0])


def test_bootstrap_intent_is_append_preserving_and_terminal(admin_conn: PgConnection) -> None:
    intent_id = _intent(admin_conn)
    admin_conn.execute(
        """
        UPDATE request_engine.platform_bootstrap_intents
           SET status = 'consumed', revision = revision + 1,
               consumed_at = clock_timestamp()
         WHERE id = %s
        """,
        (intent_id,),
    )
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.platform_bootstrap_intents WHERE id = %s",
        (intent_id,),
    ).fetchone() == ("consumed", 2)

    with pytest.raises(Error) as second_transition:
        admin_conn.execute(
            """
            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'revoked', revision = revision + 1,
                   consumed_at = NULL, revoked_at = clock_timestamp()
             WHERE id = %s
            """,
            (intent_id,),
        )
    assert second_transition.value.sqlstate == "55000"

    with pytest.raises(Error) as deletion:
        admin_conn.execute(
            "DELETE FROM request_engine.platform_bootstrap_intents WHERE id = %s",
            (intent_id,),
        )
    assert deletion.value.sqlstate == "55000"


def test_bootstrap_intent_secret_and_scope_are_immutable(admin_conn: PgConnection) -> None:
    intent_id = _intent(admin_conn)
    with pytest.raises(Error) as mutation:
        admin_conn.execute(
            """
            UPDATE request_engine.platform_bootstrap_intents
               SET token_digest = %s,
                   status = 'revoked', revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = %s
            """,
            (bytes(reversed(range(32))), intent_id),
        )
    assert mutation.value.sqlstate == "55000"


def test_runtime_app_cannot_observe_or_mutate_bootstrap_intents(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    _intent(admin_conn)
    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        with pytest.raises(Error) as read_denied:
            app_conn.execute("SELECT id FROM request_engine.platform_bootstrap_intents")
        assert read_denied.value.sqlstate == "42501"
        with pytest.raises(Error) as insert_denied:
            app_conn.execute(
                """
                INSERT INTO request_engine.platform_bootstrap_intents (
                    id, token_digest, token_fingerprint, provenance_reference, expires_at
                ) VALUES (%s, %s, '0123456789abcdef', 'runtime',
                          clock_timestamp() + interval '15 minutes')
                """,
                (uuid4(), bytes(range(32))),
            )
        assert insert_denied.value.sqlstate == "42501"
    finally:
        app_conn.close()


def test_trust_bootstrap_provenance_cannot_seed_tenant_authority(
    admin_conn: PgConnection,
) -> None:
    organization_id, principal_id = _tenant_principal(admin_conn)
    with pytest.raises(Error) as tenant_bootstrap:
        admin_conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, provenance_kind, provenance_reference
            ) VALUES (%s, %s, 'tenant', 'tenant_control',
                      'staff.manage_authority', true, 'trust_bootstrap', 'forbidden')
            """,
            (organization_id, principal_id),
        )
    assert tenant_bootstrap.value.sqlstate == "23514"
