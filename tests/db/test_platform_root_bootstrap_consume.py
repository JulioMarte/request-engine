from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

from request_engine.platform.security.native_auth import hash_password

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _authority(conn: PgConnection) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"platform-root-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _intent(conn: PgConnection) -> tuple[UUID, bytes]:
    intent_id = uuid4()
    digest = uuid4().bytes + uuid4().bytes
    conn.execute(
        """
        INSERT INTO request_engine.platform_bootstrap_intents (
            id, token_digest, token_fingerprint, provenance_reference, expires_at
        ) VALUES (%s, %s, %s, %s, clock_timestamp() + interval '15 minutes')
        """,
        (intent_id, digest, digest.hex()[:16], f"deployment:{uuid4().hex}"),
    )
    return intent_id, digest


def _establish(
    conn: PgConnection,
    *,
    intent_id: UUID,
    digest: bytes,
    authority_id: UUID,
    login: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    native_identity_id = uuid4()
    credential_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    row = conn.execute(
        """
        SELECT request_platform.establish_root(
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            intent_id,
            digest,
            authority_id,
            native_identity_id,
            login,
            credential_id,
            hash_password("correct horse battery staple"),
            principal_id,
            binding_id,
        ),
    ).fetchone()
    assert row == (principal_id,)
    return native_identity_id, credential_id, principal_id, binding_id


def test_root_establishment_materializes_one_native_platform_controller_atomically(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    intent_id, digest = _intent(admin_conn)
    native_id, credential_id, principal_id, binding_id = _establish(
        admin_conn,
        intent_id=intent_id,
        digest=digest,
        authority_id=authority_id,
        login=f"root-{uuid4().hex}",
    )

    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.platform_bootstrap_intents WHERE id = %s",
        (intent_id,),
    ).fetchone() == ("consumed", 2)
    assert admin_conn.execute(
        "SELECT identity_authority_id, status FROM request_engine.native_identities WHERE id = %s",
        (native_id,),
    ).fetchone() == (authority_id, "active")
    assert admin_conn.execute(
        "SELECT native_identity_id, status FROM request_engine.native_credentials WHERE id = %s",
        (credential_id,),
    ).fetchone() == (native_id, "active")
    assert admin_conn.execute(
        "SELECT principal_plane, principal_kind, active, authority_revision "
        "FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == ("platform", "human", True, 6)
    assert admin_conn.execute(
        "SELECT principal_id, principal_plane, status, subject_id "
        "FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == (principal_id, "platform", "active", str(native_id))

    grants = admin_conn.execute(
        """
        SELECT capability_key, delegable, provenance_kind
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s
         ORDER BY capability_key
        """,
        (principal_id,),
    ).fetchall()
    assert grants == [
        ("organization.provision", True, "trust_bootstrap"),
        ("platform.identity.recover", False, "trust_bootstrap"),
        ("platform.principal.provision", True, "trust_bootstrap"),
        ("platform.tenant_provisioner.provision", True, "trust_bootstrap"),
    ]


def test_invalid_or_consumed_intent_never_materializes_an_identity(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    intent_id, digest = _intent(admin_conn)
    before = admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone()

    row = admin_conn.execute(
        "SELECT request_platform.establish_root(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            intent_id,
            uuid4().bytes + uuid4().bytes,
            authority_id,
            uuid4(),
            f"invalid-{uuid4().hex}",
            uuid4(),
            hash_password("correct horse battery staple"),
            uuid4(),
            uuid4(),
        ),
    ).fetchone()
    assert row == (None,)
    assert admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == before

    _establish(
        admin_conn,
        intent_id=intent_id,
        digest=digest,
        authority_id=authority_id,
        login=f"root-{uuid4().hex}",
    )
    row = admin_conn.execute(
        "SELECT request_platform.establish_root(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            intent_id,
            digest,
            authority_id,
            uuid4(),
            f"repeat-{uuid4().hex}",
            uuid4(),
            hash_password("correct horse battery staple"),
            uuid4(),
            uuid4(),
        ),
    ).fetchone()
    assert row == (None,)


def test_second_bootstrap_intent_cannot_create_another_platform_root(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    first_intent, first_digest = _intent(admin_conn)
    _establish(
        admin_conn,
        intent_id=first_intent,
        digest=first_digest,
        authority_id=authority_id,
        login=f"root-{uuid4().hex}",
    )
    second_intent, second_digest = _intent(admin_conn)

    with pytest.raises(Error) as duplicate_root:
        _establish(
            admin_conn,
            intent_id=second_intent,
            digest=second_digest,
            authority_id=authority_id,
            login=f"second-{uuid4().hex}",
        )
    assert duplicate_root.value.sqlstate == "55000"
