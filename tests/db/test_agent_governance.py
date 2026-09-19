import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    issue_agent_secret,
    provision_agent,
    provision_root,
    reset_actor,
    set_tenant_actor,
    transition_agent,
    workload_authority,
)
from psycopg import Connection, Error

from request_engine.platform.db.workload_credential_reader import (
    PostgresWorkloadCredentialReader,
)
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


@pytest.mark.asyncio
async def test_agent_provisioning_creates_workload_trust_root_and_bearer_authenticates(
    admin_conn: PgConnection,
    command_session_factory: Any,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, binding_id, workload_identity_id, credential_id, token = provision_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    profile = admin_conn.execute(
        """
        SELECT status, operating_mode, sponsor_principal_id, workload_identity_id
          FROM request_engine.agent_profiles
         WHERE principal_id = %s
        """,
        (agent_principal_id,),
    ).fetchone()
    assert profile is not None
    assert profile[0] == "pending"
    assert profile[1] == "autonomous"
    assert profile[2] == controller_id
    assert profile[3] == workload_identity_id

    principal = admin_conn.execute(
        """
        SELECT principal_plane, principal_kind, active, external_subject
          FROM request_engine.principals
         WHERE id = %s
        """,
        (agent_principal_id,),
    ).fetchone()
    assert principal == ("tenant", "agent", True, f"workload:{workload_identity_id}")

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
        "agent",
    )
    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(
            WorkloadCredentialEvidence(f"{credential_id}.{secrets.token_urlsafe(32)}")
        )


def test_agent_authority_is_bounded_by_operational_ceiling(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as tenant_control_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
                (agent_principal_id, [_STAFF_CAPABILITY], f"grant:{uuid4().hex}"),
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
                "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
                (agent_principal_id, [_STAFF_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert staff_denied.value.sqlstate == "42501"

        with pytest.raises(Error) as unowned_denied:
            admin_conn.execute(
                "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
                (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
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
            "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
            (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
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
        (agent_principal_id,),
    ).fetchone()
    assert grant == ("operational", False, "agent_authority_management")


@pytest.mark.asyncio
async def test_agent_lifecycle_suspend_and_revoke_kill_authorization(
    admin_conn: PgConnection,
    command_session_factory: Any,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, binding_id, workload_identity_id, credential_id, token = provision_agent(
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
            "SELECT request_engine.replace_agent_authority(%s, 1, %s, %s)",
            (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
        ).fetchone()
        assert revision_row is not None
    finally:
        reset_actor(conn=admin_conn)

    activated = transition_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        expected_revision=1,
        target_status="active",
    )
    assert activated == 2
    binding = admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert binding == ("active",)

    suspended = transition_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        expected_revision=2,
        target_status="suspended",
    )
    assert suspended == 3
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (agent_principal_id,),
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
                "SELECT request_engine.replace_agent_authority(%s, 2, %s, %s)",
                (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert suspended_denied.value.sqlstate == "55000"
    finally:
        reset_actor(conn=admin_conn)

    revoked = transition_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        agent_principal_id=agent_principal_id,
        expected_revision=3,
        target_status="revoked",
    )
    assert revoked == 4
    credential_status = admin_conn.execute(
        "SELECT status FROM request_engine.workload_credentials WHERE id = %s",
        (credential_id,),
    ).fetchone()
    assert credential_status == ("revoked",)
    identity_status = admin_conn.execute(
        "SELECT status FROM request_engine.workload_identities WHERE id = %s",
        (workload_identity_id,),
    ).fetchone()
    assert identity_status == ("disabled",)
    authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(command_session_factory)
    )
    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(WorkloadCredentialEvidence(token))


def test_agent_provisioning_rejects_self_provisioning_and_nonhuman_sponsor(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    digest, _secret = issue_agent_secret()
    set_tenant_actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        with pytest.raises(Error) as self_provision:
            admin_conn.execute(
                """
                SELECT request_engine.provision_agent(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'autonomous', %s
                )
                """,
                (
                    controller_id,
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    workload_authority_id,
                    digest,
                    digest.hex()[:16],
                    datetime.now(UTC) + timedelta(days=30),
                    "Self Agent",
                    "self provisioning attempt",
                    controller_id,
                    f"agent-provision:{uuid4().hex}",
                ),
            )
        assert self_provision.value.sqlstate == "22023"

        with pytest.raises(Error) as agent_sponsor:
            admin_conn.execute(
                """
                SELECT request_engine.provision_agent(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'autonomous', %s
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
                    "Sponsored By Agent",
                    "agent sponsor attempt",
                    agent_principal_id,
                    f"agent-provision:{uuid4().hex}",
                ),
            )
        assert agent_sponsor.value.sqlstate == "23514"
    finally:
        reset_actor(conn=admin_conn)


def test_agent_profiles_are_tenant_isolated(
    admin_conn: PgConnection,
) -> None:
    first_org, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    second_org, _second_party, _second_controller, _second_authority = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
        admin_conn,
        organization_id=first_org,
        controller_id=controller_id,
        workload_authority_id=workload_authority_id,
    )

    set_tenant_actor(
        admin_conn,
        organization_id=second_org,
        principal_id=controller_id,
    )
    try:
        visible = admin_conn.execute(
            "SELECT count(*) FROM request_engine.agent_profiles WHERE principal_id = %s",
            (agent_principal_id,),
        ).fetchone()
        assert visible is not None
        assert int(visible[0]) == 0
    finally:
        reset_actor(conn=admin_conn)


def test_agent_authority_replacement_fails_closed_on_stale_revision(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    agent_principal_id, _binding_id, _identity_id, _credential_id, _token = provision_agent(
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
        with pytest.raises(Error) as stale:
            admin_conn.execute(
                "SELECT request_engine.replace_agent_authority(%s, 99, %s, %s)",
                (agent_principal_id, [_BOOKING_CAPABILITY], f"grant:{uuid4().hex}"),
            )
        assert stale.value.sqlstate == "40001"
    finally:
        reset_actor(conn=admin_conn)
