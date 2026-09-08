from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_CONTROL_CAPABILITIES = (
    "agent.manage_authority",
    "agent.provision",
    "agent.suspend",
    "identity.bind",
    "staff.invite",
    "staff.manage_authority",
    "staff.manage_membership",
)
_OPERATIONAL_SCOPES = (
    "manage_commercial_terms",
    "manage_contextual_supply",
    "manage_discovery",
    "manage_operational_profile",
)


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _native_identity(
    conn: PgConnection,
    *,
    credentialed: bool = True,
) -> tuple[UUID, UUID]:
    authority_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-root-{uuid4().hex}",),
    )
    native_identity_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.native_identities (
            identity_authority_id, login_handle
        ) VALUES (%s, %s) RETURNING id
        """,
        (authority_id, f"root-{uuid4().hex}@example.test"),
    )
    if credentialed:
        conn.execute(
            """
            INSERT INTO request_engine.native_credentials (
                native_identity_id, verifier
            ) VALUES (%s, %s)
            """,
            (native_identity_id, "scrypt$" + ("x" * 64)),
        )
    return authority_id, native_identity_id


def _provisioner(conn: PgConnection) -> UUID:
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"tenant-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (
            %s, 'platform', 'platform', 'organization.provision', false,
            'trust_bootstrap', %s
        )
        """,
        (principal_id, f"tenant-root:{uuid4().hex}"),
    )
    return principal_id


def _principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _provision(
    conn: PgConnection,
    *,
    provisioner: UUID,
    organization_id: UUID,
    party_id: UUID,
    controller_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
    provenance: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(_principal_revision(conn, provisioner)),),
    )
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"org-{organization_id.hex}",
                "Native Tenant",
                party_id,
                controller_id,
                authority_id,
                native_identity_id,
                provenance,
            ),
        ).fetchone()
        assert row is not None
        return (
            cast(UUID, row[0]),
            cast(UUID, row[1]),
            cast(UUID, row[2]),
            cast(UUID, row[3]),
        )
    finally:
        conn.execute("RESET ROLE")


def test_platform_provisioner_creates_complete_tenant_root_without_joining_tenant(
    admin_conn: PgConnection,
) -> None:
    provisioner = _provisioner(admin_conn)
    authority_id, native_identity_id = _native_identity(admin_conn)
    organization_id = uuid4()
    party_id = uuid4()
    controller_id = uuid4()
    provenance = f"tenant-root:{uuid4().hex}"

    created = _provision(
        admin_conn,
        provisioner=provisioner,
        organization_id=organization_id,
        party_id=party_id,
        controller_id=controller_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
        provenance=provenance,
    )
    returned_org, returned_party, returned_controller, binding_id = created
    assert (returned_org, returned_party, returned_controller) == (
        organization_id,
        party_id,
        controller_id,
    )

    assert admin_conn.execute(
        "SELECT display_name FROM request_engine.organizations WHERE id = %s",
        (organization_id,),
    ).fetchone() == ("Native Tenant",)
    assert admin_conn.execute(
        """
        SELECT party_kind, display_name, status, created_by_principal_id
          FROM request_engine.parties WHERE id = %s
        """,
        (party_id,),
    ).fetchone() == ("organization", "Native Tenant", "active", None)
    revision = admin_conn.execute(
        """
        SELECT revision, change_kind, actor_principal_id, attributed_operator_principal_id
          FROM request_engine.party_identity_revisions
         WHERE organization_id = %s AND party_id = %s
        """,
        (organization_id, party_id),
    ).fetchone()
    assert revision == (1, "registered", None, None)

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
    assert grants == [(key, True, provisioner) for key in _CONTROL_CAPABILITIES]
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
        """
        SELECT count(*)
          FROM request_engine.representations
         WHERE organization_id = %s AND principal_id = %s
        """,
        (organization_id, provisioner),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s
        """,
        (organization_id, provisioner),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT provisioned_by_principal_id, controller_principal_id,
               controller_identity_binding_id, provenance_reference
          FROM request_engine.organization_root_provisioning_facts
         WHERE organization_id = %s
        """,
        (organization_id,),
    ).fetchone() == (provisioner, controller_id, binding_id, provenance)

    replay = _provision(
        admin_conn,
        provisioner=provisioner,
        organization_id=organization_id,
        party_id=party_id,
        controller_id=controller_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
        provenance=provenance,
    )
    assert replay == created

    with pytest.raises(Error) as conflict:
        _provision(
            admin_conn,
            provisioner=provisioner,
            organization_id=organization_id,
            party_id=party_id,
            controller_id=uuid4(),
            authority_id=authority_id,
            native_identity_id=native_identity_id,
            provenance=provenance,
        )
    assert conflict.value.sqlstate == "23505"


def test_native_root_requires_active_credentialed_identity(admin_conn: PgConnection) -> None:
    provisioner = _provisioner(admin_conn)
    authority_id, native_identity_id = _native_identity(admin_conn, credentialed=False)
    with pytest.raises(Error) as rejected:
        _provision(
            admin_conn,
            provisioner=provisioner,
            organization_id=uuid4(),
            party_id=uuid4(),
            controller_id=uuid4(),
            authority_id=authority_id,
            native_identity_id=native_identity_id,
            provenance=f"tenant-root:{uuid4().hex}",
        )
    assert rejected.value.sqlstate == "23514"
