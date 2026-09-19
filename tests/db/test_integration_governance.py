from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    issue_agent_secret,
    provision_root,
    reset_actor,
    set_tenant_actor,
    workload_authority,
)
from integration_governance_support import (
    grant_integration_control,
    provision_integration,
    transition_integration,
)
from psycopg import Connection, Error

from request_engine.platform.db.workload_credential_reader import (
    PostgresWorkloadCredentialReader,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.workload_auth import (
    WorkloadCredentialAuthenticator,
    WorkloadCredentialEvidence,
    WorkloadCredentialInvalid,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_BOOKING_CAPABILITY = "appointments.book"
_STAFF_CAPABILITY = "staff.invite"


def _grant_integration_control(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    capability_key: str,
) -> None:
    grant_delegable(
        conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=capability_key,
        authority_plane="tenant_control",
    )


@pytest.mark.asyncio
async def test_integration_provisioning_creates_workload_trust_root_and_bearer_authenticates(
    admin_conn: PgConnection,
    command_session_factory: Any,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    (
        integration_principal_id,
        binding_id,
        workload_identity_id,
        credential_id,
        token,
    ) = provision_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    principal = admin_conn.execute(
        """
        SELECT principal_plane, principal_kind, active, authority_revision, external_subject
          FROM request_engine.principals
         WHERE id = %s
        """,
        (integration_principal_id,),
    ).fetchone()
    assert principal == (
        "tenant",
        "integration",
        True,
        1,
        f"workload:{workload_identity_id}",
    )

    binding = admin_conn.execute(
        "SELECT status, subject_id FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert binding == ("pending", str(workload_identity_id))

    _digest_only_stored = admin_conn.execute(
        """
        SELECT token_digest IS NOT NULL AND octet_length(token_digest) = 32
          FROM request_engine.workload_credentials
         WHERE id = %s
        """,
        (credential_id,),
    ).fetchone()
    assert _digest_only_stored == (True,)

    authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(command_session_factory)
    )
    subject = await authenticator.authenticate(WorkloadCredentialEvidence(token))
    assert (subject.subject_class.value, subject.metadata["workload_kind"]) == (
        "workload",
        "integration",
    )
    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(
            WorkloadCredentialEvidence(f"{credential_id}.{uuid4().hex}")
        )


@pytest.mark.asyncio
async def test_integration_provisioning_replay_is_idempotent_and_hides_token(
    admin_conn: PgConnection,
    command_session_factory: Any,
) -> None:
    from request_engine.modules.tenancy.adapters.db.integration_governance_commands import (
        PostgresIntegrationGovernanceCommands,
    )
    from request_engine.modules.tenancy.application.commands.integration_governance import (
        ProvisionIntegrationCommand,
    )

    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    _grant_integration_control(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        capability_key="integration.provision",
    )
    workload_authority_id = workload_authority(admin_conn)
    actor = ActorContext(
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=frozenset({"integration.provision"}),
        principal_kind=PrincipalKind.HUMAN,
        authentication_method="native_password",
    )
    commands = PostgresIntegrationGovernanceCommands(command_session_factory)
    command = ProvisionIntegrationCommand(
        identity_authority_id=workload_authority_id,
        credential_expires_at=datetime.now(UTC) + timedelta(days=30),
        provenance_reference=f"integration-replay:{uuid4().hex}",
        idempotency_key=f"integration-provision-{uuid4().hex}",
    )
    first = await commands.provision_integration(actor, command)
    assert first.authority_revision == 1
    assert first.workload_token is not None

    replayed = await commands.provision_integration(actor, command)
    assert replayed.principal_id == first.principal_id
    assert replayed.workload_identity_id == first.workload_identity_id
    assert replayed.credential_id == first.credential_id
    assert replayed.binding_id == first.binding_id
    assert replayed.authority_revision == first.authority_revision
    assert replayed.workload_token is None

    distinct = await commands.provision_integration(
        actor,
        ProvisionIntegrationCommand(
            identity_authority_id=workload_authority_id,
            credential_expires_at=datetime.now(UTC) + timedelta(days=30),
            provenance_reference=f"integration-replay:{uuid4().hex}",
            idempotency_key=f"integration-provision-{uuid4().hex}",
        ),
    )
    assert distinct.principal_id != first.principal_id
    assert distinct.workload_token is not None


def test_integration_authority_is_bounded_by_operational_ceiling(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    integration_principal_id, _binding_id, _identity_id, _credential_id, _token = (
        provision_integration(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            workload_authority_id=workload_authority_id,
        )
    )

    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as tenant_control_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_integration_authority(%s, 1, %s, %s)",
                (integration_principal_id, [_STAFF_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert tenant_control_denied.value.sqlstate == "42501"
    finally:
        reset_actor(conn=admin_conn)

    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_STAFF_CAPABILITY,
        authority_plane="tenant_control",
    )
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as staff_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_integration_authority(%s, 1, %s, %s)",
                (integration_principal_id, [_STAFF_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert staff_denied.value.sqlstate == "42501"

        with pytest.raises(Error) as unowned_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_integration_authority(%s, 1, %s, %s)",
                (integration_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert unowned_denied.value.sqlstate == "42501"
    finally:
        reset_actor(conn=admin_conn)

    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_BOOKING_CAPABILITY,
        authority_plane="operational",
    )
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        row = admin_conn.execute(
            "SELECT request_engine.replace_integration_authority(%s, 1, %s, %s)",
            (integration_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
        ).fetchone()
        assert row is not None and int(row[0]) == 2
    finally:
        reset_actor(conn=admin_conn)

    grant = admin_conn.execute(
        """
        SELECT authority_plane, delegable, provenance_kind
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active'
        """,
        (integration_principal_id,),
    ).fetchone()
    assert grant == ("operational", False, "integration_authority_management")


def test_integration_authority_replacement_fails_closed_on_stale_revision(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    integration_principal_id, _binding_id, _identity_id, _credential_id, _token = (
        provision_integration(
            admin_conn,
            organization_id=organization_id,
            controller_id=controller_id,
            workload_authority_id=workload_authority_id,
        )
    )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_BOOKING_CAPABILITY,
        authority_plane="operational",
    )

    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as stale:
            admin_conn.execute(
                "SELECT request_engine.replace_integration_authority(%s, 99, %s, %s)",
                (integration_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert stale.value.sqlstate == "40001"
    finally:
        reset_actor(conn=admin_conn)


def test_integration_provisioning_rejects_self_provisioning_and_bad_authority(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    native_authority_id = admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"integration-native-{uuid4().hex}",),
    ).fetchone()
    assert native_authority_id is not None
    native_authority_id = native_authority_id[0]

    digest, _secret = issue_agent_secret()
    grant_integration_control(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
    )
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as self_provision:
            admin_conn.execute(
                """
                SELECT request_engine.provision_integration(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    controller_id,
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    native_authority_id,
                    digest,
                    digest.hex()[:16],
                    datetime.now(UTC) + timedelta(days=30),
                    f"integration-self:{uuid4().hex}",
                ),
            )
        # Current boundary rejects every occupied Principal identifier before
        # invoking provisioning; a HUMAN cannot be overwritten as INTEGRATION.
        assert self_provision.value.sqlstate == "23505"
        assert admin_conn.execute(
            "SELECT principal_kind FROM request_engine.principals WHERE id = %s",
            (controller_id,),
        ).fetchone() == ("human",)

        with pytest.raises(Error) as bad_authority:
            admin_conn.execute(
                """
                SELECT request_engine.provision_integration(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    native_authority_id,
                    digest,
                    digest.hex()[:16],
                    datetime.now(UTC) + timedelta(days=30),
                    f"integration-native:{uuid4().hex}",
                ),
            )
        assert bad_authority.value.sqlstate == "23514"
    finally:
        reset_actor(conn=admin_conn)


def test_integration_governance_denies_non_human_actor(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    (
        integration_principal_id,
        _binding_id,
        _identity_id,
        _credential_id,
        _token,
    ) = provision_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )
    _grant_integration_control(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        capability_key="integration.provision",
    )

    transition_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        integration_principal_id=integration_principal_id,
        expected_revision=1,
        target_status="active",
    )
    digest, _secret = issue_agent_secret()
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=integration_principal_id,
    )
    try:
        with pytest.raises(Error) as integration_actor:
            admin_conn.execute(
                """
                SELECT request_engine.provision_integration(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    workload_authority_id,
                    digest,
                    digest.hex()[:16],
                    datetime.now(UTC) + timedelta(days=30),
                    f"integration-actor:{uuid4().hex}",
                ),
            )
        assert integration_actor.value.sqlstate == "42501"
    finally:
        reset_actor(conn=admin_conn)


def test_integrations_are_tenant_isolated(
    admin_conn: PgConnection,
) -> None:
    first_org, _party_id, _controller_id, _authority_id = provision_root(admin_conn)
    second_org, _second_party, second_controller, _second_authority = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    integration_principal_id, _binding_id, _identity_id, _credential_id, _token = (
        provision_integration(
            admin_conn,
            organization_id=first_org,
            controller_id=_controller_id,
            workload_authority_id=workload_authority_id,
        )
    )
    grant_integration_control(
        admin_conn,
        organization_id=second_org,
        controller_id=second_controller,
    )

    set_tenant_actor(
        admin_conn,
        organization_id=second_org,
        principal_id=second_controller,
    )
    try:
        with pytest.raises(Error) as hidden:
            admin_conn.execute(
                "SELECT request_engine.set_integration_status(%s, 1, 'active', %s)",
                (integration_principal_id, f"integration-cross:{uuid4().hex}"),
            )
        assert hidden.value.sqlstate == "P0002"
        visible = admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.principals
             WHERE id = %s AND principal_kind = 'integration'
            """,
            (integration_principal_id,),
        ).fetchone()
        assert visible is not None
        assert int(visible[0]) == 0
    finally:
        reset_actor(conn=admin_conn)


@pytest.mark.asyncio
async def test_integration_lifecycle_suspend_and_revoke_kill_authorization(
    admin_conn: PgConnection,
    command_session_factory: Any,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    (
        integration_principal_id,
        binding_id,
        workload_identity_id,
        credential_id,
        token,
    ) = provision_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_BOOKING_CAPABILITY,
        authority_plane="operational",
    )
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        revision_row = admin_conn.execute(
            "SELECT request_engine.replace_integration_authority(%s, 1, %s, %s)",
            (integration_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
        ).fetchone()
        assert revision_row is not None
    finally:
        reset_actor(conn=admin_conn)

    activated = transition_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        integration_principal_id=integration_principal_id,
        expected_revision=2,
        target_status="active",
    )
    assert activated == 3
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (integration_principal_id,),
    ).fetchone() == (True,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == ("active",)

    suspended = transition_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        integration_principal_id=integration_principal_id,
        expected_revision=3,
        target_status="suspended",
    )
    assert suspended == 5
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (integration_principal_id,),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == ("suspended",)

    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as suspended_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_integration_authority(%s, 5, %s, %s)",
                (integration_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert suspended_denied.value.sqlstate == "55000"
    finally:
        reset_actor(conn=admin_conn)

    revoked = transition_integration(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        integration_principal_id=integration_principal_id,
        expected_revision=5,
        target_status="revoked",
    )
    assert revoked == 6
    assert admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.workload_credentials
         WHERE id = %s AND status = 'active'
        """,
        (credential_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.workload_identities
         WHERE id = %s AND status = 'active'
        """,
        (workload_identity_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.identity_bindings
         WHERE principal_id = %s AND status <> 'revoked'
        """,
        (integration_principal_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.workload_credentials WHERE id = %s",
        (credential_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.workload_identities WHERE id = %s",
        (workload_identity_id,),
    ).fetchone() == ("disabled",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone() == ("revoked",)

    authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(command_session_factory)
    )
    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(WorkloadCredentialEvidence(token))
