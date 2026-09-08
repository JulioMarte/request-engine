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

_CONTROL_CAPABILITIES = {
    "agent.manage_authority",
    "agent.provision",
    "agent.suspend",
    "identity.bind",
    "staff.invite",
    "staff.manage_authority",
    "staff.manage_membership",
}


def _uuid_row(conn: PgConnection, query: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _native_identity(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    authority_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"staff-native-{uuid4().hex}",),
    )
    identity_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.native_identities (
            identity_authority_id, login_handle
        ) VALUES (%s, %s) RETURNING id
        """,
        (authority_id, f"staff-{uuid4().hex}@example.test"),
    )
    credential_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.native_credentials (
            native_identity_id, verifier
        ) VALUES (%s, %s) RETURNING id
        """,
        (identity_id, "scrypt$" + ("x" * 64)),
    )
    return authority_id, identity_id, credential_id


def _principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _provision_root(
    conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"staff-platform-{uuid4().hex}",),
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
        (provisioner_id, f"staff-root:{uuid4().hex}"),
    )
    authority_id, native_identity_id, _credential_id = _native_identity(conn)
    organization_id = uuid4()
    party_id = uuid4()
    controller_id = uuid4()
    provenance = f"staff-root:{uuid4().hex}"

    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(_principal_revision(conn, provisioner_id)),),
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
                f"staff-tenant-{organization_id.hex}",
                "Staff Tenant",
                party_id,
                controller_id,
                authority_id,
                native_identity_id,
                provenance,
            ),
        ).fetchone()
        assert row is not None
        binding_id = cast(UUID, row[3])
    finally:
        conn.execute("RESET ROLE")
    return organization_id, party_id, controller_id, binding_id, provisioner_id


def _set_tenant_actor(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    conn.execute("SET ROLE request_engine_app")


def _invite_and_activate(
    conn: PgConnection,
    *,
    organization_id: UUID,
    root_id: UUID,
    party_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    _set_tenant_actor(
        conn,
        organization_id=organization_id,
        principal_id=root_id,
    )
    try:
        returned = conn.execute(
            """
            SELECT request_engine.invite_native_staff(
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"staff-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            """
            SELECT request_engine.transition_staff_membership(
                %s, 1, 'active', %s
            )
            """,
            (membership_id, f"staff-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
    finally:
        conn.execute("RESET ROLE")
    return membership_id, principal_id, binding_id


def test_root_bootstrap_materializes_active_staff_with_delegable_control(
    admin_conn: PgConnection,
) -> None:
    organization_id, party_id, controller_id, binding_id, provisioner_id = _provision_root(
        admin_conn
    )
    membership = admin_conn.execute(
        """
        SELECT principal_id, identity_binding_id, authority_anchor_party_id,
               status, revision, established_by_principal_id, provenance_kind
          FROM request_engine.staff_memberships
         WHERE organization_id = %s
        """,
        (organization_id,),
    ).fetchone()
    assert membership == (
        controller_id,
        binding_id,
        party_id,
        "active",
        1,
        provisioner_id,
        "root_provisioning",
    )

    grants = admin_conn.execute(
        """
        SELECT capability_key, delegable
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s
           AND authority_plane = 'tenant_control'
           AND status = 'active'
        """,
        (controller_id,),
    ).fetchall()
    assert {cast(str, key) for key, _delegable in grants} == _CONTROL_CAPABILITIES
    assert all(bool(delegable) for _key, delegable in grants)


def test_staff_authority_replace_is_bounded_by_delegable_ceiling(
    admin_conn: PgConnection,
) -> None:
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(
        admin_conn
    )
    authority_id, native_identity_id, _credential_id = _native_identity(admin_conn)
    membership_id, staff_id, _staff_binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
    )
    expected_revision = _principal_revision(admin_conn, staff_id)

    _set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
    )
    try:
        replaced = admin_conn.execute(
            """
            SELECT request_engine.replace_staff_authority(
                %s, %s, ARRAY['staff.invite']::text[], %s
            )
            """,
            (
                membership_id,
                expected_revision,
                f"staff-authority:{uuid4().hex}",
            ),
        ).fetchone()
        assert replaced is not None
        new_revision = int(replaced[0])
        assert new_revision > expected_revision

        with pytest.raises(Error) as amplification:
            admin_conn.execute(
                """
                SELECT request_engine.replace_staff_authority(
                    %s, %s, ARRAY['appointments.cancel']::text[], %s
                )
                """,
                (
                    membership_id,
                    new_revision,
                    f"staff-amplify:{uuid4().hex}",
                ),
            )
        assert amplification.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")

    active = admin_conn.execute(
        """
        SELECT capability_key, delegable
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active'
        """,
        (staff_id,),
    ).fetchall()
    assert active == [("staff.invite", False)]


def test_staff_suspension_disables_principal_and_revokes_native_session(
    admin_conn: PgConnection,
) -> None:
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(
        admin_conn
    )
    authority_id, native_identity_id, credential_id = _native_identity(admin_conn)
    membership_id, staff_id, staff_binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
    )
    session_id = uuid4()
    epoch_row = admin_conn.execute(
        "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
        (native_identity_id,),
    ).fetchone()
    assert epoch_row is not None
    admin_conn.execute(
        """
        INSERT INTO request_engine.native_sessions (
            id, native_identity_id, credential_id, token_digest,
            token_fingerprint, session_epoch, expires_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, clock_timestamp() + interval '1 hour'
        )
        """,
        (
            session_id,
            native_identity_id,
            credential_id,
            b"s" * 32,
            uuid4().hex[:16],
            int(epoch_row[0]),
        ),
    )

    _set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
    )
    try:
        transitioned = admin_conn.execute(
            """
            SELECT request_engine.transition_staff_membership(
                %s, 2, 'suspended', %s
            )
            """,
            (membership_id, f"staff-suspend:{uuid4().hex}"),
        ).fetchone()
        assert transitioned == (3,)
    finally:
        admin_conn.execute("RESET ROLE")

    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (staff_id,),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (staff_binding_id,),
    ).fetchone() == ("suspended",)
    assert admin_conn.execute(
        "SELECT status, revocation_reason FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone() == ("revoked", "staff_suspended")


def test_last_recovery_capable_controller_cannot_be_removed(
    admin_conn: PgConnection,
) -> None:
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(
        admin_conn
    )
    authority_id, native_identity_id, _credential_id = _native_identity(admin_conn)
    membership_id, staff_id, _staff_binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
    )
    staff_revision = _principal_revision(admin_conn, staff_id)

    _set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
    )
    try:
        replacement = admin_conn.execute(
            """
            SELECT request_engine.replace_staff_authority(
                %s, %s,
                ARRAY[
                    'staff.manage_membership',
                    'staff.manage_authority',
                    'identity.bind'
                ]::text[],
                %s
            )
            """,
            (
                membership_id,
                staff_revision,
                f"staff-controller:{uuid4().hex}",
            ),
        ).fetchone()
        assert replacement is not None
    finally:
        admin_conn.execute("RESET ROLE")

    root_membership_row = admin_conn.execute(
        "SELECT id, revision FROM request_engine.staff_memberships WHERE principal_id = %s",
        (root_id,),
    ).fetchone()
    assert root_membership_row is not None
    root_membership_id = cast(UUID, root_membership_row[0])
    root_membership_revision = int(root_membership_row[1])

    _set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=staff_id,
    )
    try:
        removed = admin_conn.execute(
            """
            SELECT request_engine.transition_staff_membership(
                %s, %s, 'suspended', %s
            )
            """,
            (
                root_membership_id,
                root_membership_revision,
                f"root-suspend:{uuid4().hex}",
            ),
        ).fetchone()
        assert removed == (root_membership_revision + 1,)

        with pytest.raises(Error) as self_removal:
            admin_conn.execute(
                """
                SELECT request_engine.transition_staff_membership(
                    %s, %s, 'suspended', %s
                )
                """,
                (
                    membership_id,
                    2,
                    f"last-controller:{uuid4().hex}",
                ),
            )
        assert self_removal.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")
