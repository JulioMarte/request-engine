from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

_CONTROL_CAPABILITIES = [
    "agent.manage_authority",
    "agent.provision",
    "agent.suspend",
    "identity.bind",
    "staff.invite",
    "staff.manage_authority",
    "staff.manage_membership",
]
_OPERATIONAL_SCOPES = [
    "operations.manage_discovery",
    "operations.manage_profile",
    "operations.manage_supply",
    "operations.manage_terms",
]


def _platform_provisioner(conn: PgConnection) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"tenant-provisioner-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    principal_id = cast(UUID, row[0])
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (%s, 'platform', 'platform', 'organization.provision', false,
                  'trust_bootstrap', %s)
        """,
        (principal_id, f"proof:{uuid4().hex}"),
    )
    return principal_id


def _native_identity(conn: PgConnection, *, credentialed: bool = True) -> tuple[UUID, UUID]:
    authority_row = conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-proof-{uuid4().hex}",),
    ).fetchone()
    assert authority_row is not None
    authority_id = cast(UUID, authority_row[0])
    identity_row = conn.execute(
        """
        INSERT INTO request_engine.native_identities (
            identity_authority_id, login_handle
        ) VALUES (%s, %s) RETURNING id
        """,
        (authority_id, f"controller-{uuid4().hex}@example.test"),
    ).fetchone()
    assert identity_row is not None
    identity_id = cast(UUID, identity_row[0])
    if credentialed:
        conn.execute(
            """
            INSERT INTO request_engine.native_credentials (
                native_identity_id, verifier
            ) VALUES (%s, %s)
            """,
            (identity_id, "scrypt$" + ("x" * 64)),
        )
    return authority_id, identity_id


def _revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _set_actor(conn: PgConnection, principal_id: UUID) -> None:
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(_revision(conn, principal_id)),),
    )


def _provision_root(
    conn: PgConnection,
    *,
    organization_id: UUID,
    party_id: UUID,
    controller_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
    provenance: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    row = conn.execute(
        """
        SELECT * FROM request_platform.provision_native_organization_root(
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            organization_id,
            f"tenant-{organization_id.hex}",
            "Atomic Tenant",
            party_id,
            controller_id,
            authority_id,
            native_identity_id,
            provenance,
        ),
    ).fetchone()
    assert row is not None
    return cast(tuple[UUID, UUID, UUID, UUID], row)


def test_platform_provisioner_creates_complete_tenant_root_without_joining_tenant(
    admin_conn: PgConnection,
) -> None:
    provisioner = _platform_provisioner(admin_conn)
    authority_id, native_identity_id = _native_identity(admin_conn)
    organization_id = uuid4()
    party_id = uuid4()
    controller_id = uuid4()
    provenance = f"proof:{uuid4().hex}"

    _set_actor(admin_conn, provisioner)
    admin_conn.execute("SET ROLE request_platform_control")
    try:
        created = _provision_root(
            admin_conn,
            organization_id=organization_id,
            party_id=party_id,
            controller_id=controller_id,
            authority_id=authority_id,
            native_identity_id=native_identity_id,
            provenance=provenance,
        )
        replayed = _provision_root(
            admin_conn,
            organization_id=organization_id,
            party_id=party_id,
            controller_id=controller_id,
            authority_id=authority_id,
            native_identity_id=native_identity_id,
            provenance=provenance,
        )
        with pytest.raises(Error) as conflict:
            _provision_root(
                admin_conn,
                organization_id=organization_id,
                party_id=party_id,
                controller_id=uuid4(),
                authority_id=authority_id,
                native_identity_id=native_identity_id,
                provenance=provenance,
            )
        assert conflict.value.sqlstate == "23505"
    finally:
        admin_conn.execute("RESET ROLE")

    assert created == replayed
    assert created[:3] == (organization_id, party_id, controller_id)
    binding_id = created[3]

    assert admin_conn.execute(
        "SELECT organization_id, party_kind, display_name, active "
        "FROM request_engine.parties WHERE id = %s",
        (party_id,),
    ).fetchone() == (organization_id, "organization", "Atomic Tenant", True)
    ledger = admin_conn.execute(
        """
        SELECT revision, change_kind, display_name, active, source_kind, platform
          FROM request_engine.party_identity_revisions
         WHERE organization_id = %s AND party_id = %s
        """,
        (organization_id, party_id),
    ).fetchall()
    assert ledger == [(1, "registered", "Atomic Tenant", True, "operator", "request_engine")]

    assert admin_conn.execute(
        """
        SELECT organization_id, principal_plane, principal_kind, active
          FROM request_engine.principals WHERE id = %s
        """,
        (controller_id,),
    ).fetchone() == (organization_id, "tenant", "human", True)
    assert admin_conn.execute(
        """
        SELECT organization_id, principal_id, principal_plane, identity_authority_id,
               subject_id, status
          FROM request_engine.identity_bindings WHERE id = %s
        """,
        (binding_id,),
    ).fetchone() == (
        organization_id,
        controller_id,
        "tenant",
        authority_id,
        str(native_identity_id),
        "active",
    )

    grants = admin_conn.execute(
        """
        SELECT capability_key, delegable, granted_by_principal_id
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s AND status = 'active'
         ORDER BY capability_key
        """,
        (organization_id, controller_id),
    ).fetchall()
    assert grants == [(key, False, provisioner) for key in _CONTROL_CAPABILITIES]
    scopes = admin_conn.execute(
        """
        SELECT scope_key
          FROM request_engine.representations
         WHERE organization_id = %s AND principal_id = %s
           AND represented_party_id = %s AND status = 'active'
         ORDER BY scope_key
        """,
        (organization_id, controller_id, party_id),
    ).fetchall()
    assert scopes == [(scope,) for scope in _OPERATIONAL_SCOPES]

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principals WHERE organization_id = %s AND id = %s",
        (organization_id, provisioner),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE organization_id = %s AND principal_id = %s",
        (organization_id, provisioner),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations "
        "WHERE organization_id = %s AND principal_id = %s",
        (organization_id, provisioner),
    ).fetchone() == (0,)


def test_uncredentialed_native_identity_cannot_become_first_controller(
    admin_conn: PgConnection,
) -> None:
    provisioner = _platform_provisioner(admin_conn)
    authority_id, native_identity_id = _native_identity(admin_conn, credentialed=False)
    _set_actor(admin_conn, provisioner)

    admin_conn.execute("SET ROLE request_platform_control")
    try:
        with pytest.raises(Error) as rejected:
            _provision_root(
                admin_conn,
                organization_id=uuid4(),
                party_id=uuid4(),
                controller_id=uuid4(),
                authority_id=authority_id,
                native_identity_id=native_identity_id,
                provenance=f"proof:{uuid4().hex}",
            )
        assert rejected.value.sqlstate == "23514"
    finally:
        admin_conn.execute("RESET ROLE")
