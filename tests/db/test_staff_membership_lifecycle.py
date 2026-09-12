from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

from request_engine.modules.tenancy.adapters.db.staff_membership_reader import (
    PostgresStaffMembershipReader,
)
from request_engine.modules.tenancy.application.errors import StaffMembershipForbidden
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

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
    "staff.read",
}


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
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
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(admin_conn)
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
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(admin_conn)
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
    organization_id, party_id, root_id, _binding_id, _provisioner_id = _provision_root(admin_conn)
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


@pytest.mark.asyncio
async def test_staff_reads_recheck_revoked_authority_with_a_previously_valid_actor(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    """A cached trusted actor must not preserve revoked directory visibility."""
    organization_id, _, root_id, _, _ = _provision_root(admin_conn)
    actor = ActorContext(
        organization_id=organization_id,
        principal_id=root_id,
        capabilities=frozenset({"staff.read"}),
        authority_revision=_principal_revision(admin_conn, root_id),
    )
    reader = PostgresStaffMembershipReader(command_session_factory)
    members = await reader.list_memberships(actor, ListStaffMembershipsQuery())
    assert len(members) == 1
    assert members[0].principal_id == root_id
    assert await reader.read_membership(actor, members[0].membership_id) == members[0]

    # This committed change occurs after authentication, before the next read.
    # The operation under test still uses the least-privilege application role.
    revoked = admin_conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked', revision = revision + 1,
               revoked_at = clock_timestamp(), revoked_by_principal_id = %s
         WHERE organization_id = %s AND principal_id = %s
           AND capability_key = 'staff.read' AND status = 'active'
        RETURNING id
        """,
        (root_id, organization_id, root_id),
    ).fetchall()
    assert len(revoked) == 1
    assert actor.allows("staff.read")  # Deliberately retain the stale snapshot.
    with pytest.raises(StaffMembershipForbidden):
        await reader.list_memberships(actor, ListStaffMembershipsQuery())
    with pytest.raises(StaffMembershipForbidden):
        await reader.read_membership(actor, members[0].membership_id)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.principal_authority_grants WHERE id = %s",
        (revoked[0][0],),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.staff_memberships WHERE id = %s",
        (members[0].membership_id,),
    ).fetchone() == ("active", 1)


def test_suspended_staff_can_be_revoked_without_temporary_reactivation(
    admin_conn: PgConnection,
) -> None:
    organization_id, party_id, root_id, _, _ = _provision_root(admin_conn)
    authority_id, native_id, _ = _native_identity(admin_conn)
    membership_id, staff_id, binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_id,
    )
    _set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    try:
        for target, revision in (("suspended", 2), ("revoked", 3)):
            assert admin_conn.execute(
                "SELECT request_engine.transition_staff_membership(%s, %s, %s, %s)",
                (membership_id, revision, target, f"staff-terminal-{target}"),
            ).fetchone() == (revision + 1,)
        with pytest.raises(Error) as resurrection:
            admin_conn.execute(
                "SELECT request_engine.transition_staff_membership(%s, 4, 'active', %s)",
                (membership_id, "staff-terminal-resurrection"),
            )
        assert resurrection.value.sqlstate == "55000"
    finally:
        admin_conn.execute("RESET ROLE")
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.staff_memberships WHERE id = %s",
        (membership_id,),
    ).fetchone() == ("revoked", 4)
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (staff_id,),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == ("revoked",)


@pytest.mark.parametrize(
    ("revision", "reference"), [(None, "proof"), (0, "proof"), (2, None), (2, " ")]
)
def test_staff_transition_requires_revision_and_provenance_at_database_boundary(
    admin_conn: PgConnection,
    revision: int | None,
    reference: str | None,
) -> None:
    organization_id, party_id, root_id, _, _ = _provision_root(admin_conn)
    authority_id, native_id, _ = _native_identity(admin_conn)
    membership_id, staff_id, binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_id,
    )
    _set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    try:
        with pytest.raises(Error) as rejected:
            admin_conn.execute(
                "SELECT request_engine.transition_staff_membership(%s, %s, 'revoked', %s)",
                (membership_id, revision, reference),
            )
        assert rejected.value.sqlstate == "22023"
    finally:
        admin_conn.execute("RESET ROLE")
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.staff_memberships WHERE id = %s",
        (membership_id,),
    ).fetchone() == ("active", 2)
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (staff_id,),
    ).fetchone() == (True,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == ("active",)


@pytest.mark.concurrency
@pytest.mark.parametrize("winner_status", ["active", "revoked"])
def test_suspended_staff_competing_transitions_reject_stale_loser(
    admin_conn: PgConnection,
    pg_conninfo: str,
    winner_status: str,
) -> None:
    """A waiting operator cannot overwrite the committed lifecycle decision."""
    organization_id, party_id, root_id, _, _ = _provision_root(admin_conn)
    authority_id, native_id, _ = _native_identity(admin_conn)
    membership_id, staff_id, binding_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=authority_id,
        native_identity_id=native_id,
    )
    _set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    try:
        assert admin_conn.execute(
            "SELECT request_engine.transition_staff_membership(%s, 2, 'suspended', %s)",
            (membership_id, "race-precondition-suspension"),
        ).fetchone() == (3,)
    finally:
        admin_conn.execute("RESET ROLE")
    before = admin_conn.execute(
        """
        SELECT b.revision, i.session_epoch
          FROM request_engine.identity_bindings b
          JOIN request_engine.native_identities i ON i.id = %s
         WHERE b.id = %s
        """,
        (native_id, binding_id),
    ).fetchone()
    assert before is not None
    loser_status = "revoked" if winner_status == "active" else "active"

    with (
        PgConnection.connect(pg_conninfo) as winner,
        PgConnection.connect(pg_conninfo, autocommit=True) as loser,
    ):
        for conn in (winner, loser):
            conn.execute("SET statement_timeout = '10s'")
            _set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
        assert winner.execute(
            "SELECT request_engine.transition_staff_membership(%s, 3, %s, %s)",
            (membership_id, winner_status, "race-winner"),
        ).fetchone() == (4,)

        def contend() -> None:
            loser.execute(
                "SELECT request_engine.transition_staff_membership(%s, 3, %s, %s)",
                (membership_id, loser_status, "race-stale-loser"),
            ).fetchone()

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(contend)
            try:
                deadline = monotonic() + 5
                while True:
                    blocked = admin_conn.execute(
                        "SELECT %s = ANY(pg_blocking_pids(%s))",
                        (winner.info.backend_pid, loser.info.backend_pid),
                    ).fetchone()
                    if blocked == (True,):
                        break
                    assert not pending.done(), "contender bypassed the held lifecycle lock"
                    assert monotonic() < deadline, "contender never waited on the winner"
                    Event().wait(0.01)
                winner.commit()
                with pytest.raises(Error) as stale:
                    pending.result(timeout=10)
                assert stale.value.sqlstate == "40001"
            finally:
                # Release the lock even if the synchronization assertion fails.
                winner.rollback()

    assert admin_conn.execute(
        """
        SELECT m.status, m.revision, b.status, b.revision, p.active, i.session_epoch
          FROM request_engine.staff_memberships m
          JOIN request_engine.identity_bindings b ON b.id = m.identity_binding_id
          JOIN request_engine.principals p ON p.id = m.principal_id
          JOIN request_engine.native_identities i ON i.id = %s
         WHERE m.id = %s AND m.principal_id = %s
        """,
        (native_id, membership_id, staff_id),
    ).fetchone() == (
        winner_status,
        4,
        winner_status,
        int(before[0]) + 1,
        winner_status == "active",
        int(before[1]) + int(winner_status == "revoked"),
    )
