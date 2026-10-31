"""INV-STAFF-INVITATION-PROPOSAL-001 over HTTP: a Chief of Staff agent proposes, the owner decides.

The organization root is created with the current native initial controller policy
(v8), so the controller's delegable ``staff.propose_invitation`` comes from the
policy itself, not from test SQL. The agent is provisioned, authorized and given a
tool/risk policy only through the governance API.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NATIVE_INITIAL_CONTROLLER_POLICY,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import StagedRecoverySecret

from .agent_policy_support import provision_agent_policy
from .native_provisioning_support import (
    PgConnection,
    login,
    principal_revision,
    tenant_headers,
    uuid_row,
    workload_authority,
)

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]
_SIGNING_KEY = b"staff-invitation-proposal-e2e-signing-key-v1"


class _SecretStore:
    """Only the external secret backend is doubled; delivery intent stays real."""

    def __init__(self) -> None:
        self.staged: dict[tuple[UUID, int], str] = {}

    async def stage(
        self, *, case_id: UUID, generation: int, secret: str, expires_at: datetime
    ) -> StagedRecoverySecret:
        created = (case_id, generation) not in self.staged
        retained = self.staged.setdefault((case_id, generation), secret)
        return StagedRecoverySecret(
            f"e2e:{case_id}:{generation}",
            hashlib.sha256(retained.encode()).hexdigest(),
            expires_at,
            created,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.staged.pop((case_id, generation), None)


def _provision_root_with_current_policy(
    conn: PgConnection, *, authority_id: UUID, native_identity_id: UUID
) -> tuple[UUID, UUID]:
    provisioner = uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES('platform','human',%s) RETURNING id",
        (f"proposal-platform-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES(%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner, f"proposal-root:{uuid4().hex}"),
    )
    organization_id, controller_id = uuid4(), uuid4()
    with conn.transaction():
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id',%s,true),"
            "set_config('request_engine.authority_revision',%s,true)",
            (str(provisioner), str(principal_revision(conn, provisioner))),
        )
        conn.execute("SET LOCAL ROLE request_platform_control")
        conn.execute(
            "SELECT request_platform.select_initial_controller_policy(%s)",
            (NATIVE_INITIAL_CONTROLLER_POLICY,),
        )
        row = conn.execute(
            "SELECT * FROM request_platform.provision_native_organization_root("
            "%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                organization_id,
                f"proposal-{organization_id.hex}",
                "Proposal Clinic",
                uuid4(),
                controller_id,
                authority_id,
                native_identity_id,
                f"proposal-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    return organization_id, controller_id


def _invitation_count(conn: PgConnection, organization_id: UUID) -> tuple[int, int]:
    row = conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.staff_invitations WHERE organization_id=%s),"
        "(SELECT count(*) FROM request_engine.staff_invitation_deliveries "
        "WHERE organization_id=%s)",
        (organization_id, organization_id),
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


@pytest.mark.asyncio
async def test_chief_of_staff_agent_proposes_and_only_the_owner_approves_or_rejects(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = uuid_row(
        e2e_admin_conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES('native',%s) RETURNING id",
        (f"proposal-e2e-{uuid4().hex}",),
    )
    password = "owner-proposal-e2e-password-1"
    owner_identity = await build_native_auth_runtime(
        e2e_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"owner-{uuid4().hex}@example.test",
        password=password,
    )
    organization_id, owner_id = _provision_root_with_current_policy(
        e2e_admin_conn,
        authority_id=authority_id,
        native_identity_id=owner_identity.native_identity_id,
    )
    assert e2e_admin_conn.execute(
        "SELECT delegable FROM request_engine.principal_authority_grants WHERE principal_id=%s "
        "AND capability_key='staff.propose_invitation' AND status='active'",
        (owner_id,),
    ).fetchall() == [(True,)]
    store = _SecretStore()
    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
        staff_invitation_delivery=store,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await login(
            client, login_handle=owner_identity.login_handle, password=password
        )
        owner = tenant_headers(token=owner_token, organization_id=organization_id)

        provisioned = await client.post(
            "/v1/agents",
            headers={**owner, "Idempotency-Key": f"cos-{uuid4().hex}"},
            json={
                "identity_authority_id": str(workload_authority(e2e_admin_conn)),
                "display_name": "Chief of Staff",
                "purpose": "execute what the owner asks; propose staff changes for approval",
                "sponsor_principal_id": str(owner_id),
                "operating_mode": "assisted",
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "provenance_reference": "proposal-e2e-provision",
            },
        )
        assert provisioned.status_code == 201, provisioned.text
        agent_id = UUID(provisioned.json()["principal_id"])
        agent = tenant_headers(
            token=provisioned.json()["workload_token"], organization_id=organization_id
        )
        activated = await client.put(
            f"/v1/agents/{agent_id}/status",
            headers={**owner, "Idempotency-Key": f"cos-activate-{uuid4().hex}"},
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "proposal-e2e-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        assigned = await client.put(
            f"/v1/agents/{agent_id}/authority",
            headers={**owner, "Idempotency-Key": f"cos-authority-{uuid4().hex}"},
            json={
                "expected_authority_revision": principal_revision(e2e_admin_conn, agent_id),
                "desired_capabilities": ["staff.propose_invitation"],
                "provenance_reference": "proposal-e2e-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text
        # Tenant-control authority can never be delegated to an agent.
        widened = await client.put(
            f"/v1/agents/{agent_id}/authority",
            headers={**owner, "Idempotency-Key": f"cos-widen-{uuid4().hex}"},
            json={
                "expected_authority_revision": principal_revision(e2e_admin_conn, agent_id),
                "desired_capabilities": ["staff.propose_invitation", "staff.invite"],
                "provenance_reference": "proposal-e2e-widen",
            },
        )
        assert widened.status_code in {403, 422}, widened.text
        await provision_agent_policy(
            client,
            controller_headers=owner,
            agent_principal_id=agent_id,
            allowed_capabilities=["staff.propose_invitation"],
            risk_ceiling="low_impact_write",
        )

        propose_key = f"voice-{uuid4().hex}"
        body = {
            "email": "Maria.Lopez@Example.test",
            "display_name": "María López",
            "note": "Owner said: add María as receptionist",
            "provenance_reference": "owner voice request",
        }
        proposed = await client.post(
            "/v1/staff/invitation-proposals",
            headers={**agent, "Idempotency-Key": propose_key},
            json=body,
        )
        assert proposed.status_code == 201, proposed.text
        proposal = proposed.json()
        assert proposal["status"] == "pending" and proposal["revision"] == 1
        assert proposal["email"] == "maria.lopez@example.test"
        assert proposal["proposed_by_principal_id"] == str(agent_id)
        assert proposal["proposed_by_principal_kind"] == "agent"
        assert proposal["proposed_by_display_name"] == "Chief of Staff"
        assert _invitation_count(e2e_admin_conn, organization_id) == (0, 0)
        assert store.staged == {}
        replayed = await client.post(
            "/v1/staff/invitation-proposals",
            headers={**agent, "Idempotency-Key": propose_key},
            json=body,
        )
        assert replayed.status_code == 201 and replayed.json() == proposal
        duplicate = await client.post(
            "/v1/staff/invitation-proposals",
            headers={**agent, "Idempotency-Key": f"voice-{uuid4().hex}"},
            json=body,
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "staff_invitation_proposal_duplicate"
        own = await client.get(
            f"/v1/staff/invitation-proposals/{proposal['proposal_id']}", headers=agent
        )
        assert own.status_code == 200 and own.json() == proposal

        proposal_id = proposal["proposal_id"]
        approve_body = {"expected_revision": 1, "provenance_reference": "owner approved"}
        for path, payload in (
            (f"/v1/staff/invitation-proposals/{proposal_id}:approve", approve_body),
            (f"/v1/staff/invitation-proposals/{proposal_id}:reject", approve_body),
            (
                "/v1/staff/invitations",
                {"email": "maria.lopez@example.test", "provenance_reference": "agent"},
            ),
        ):
            denied = await client.post(
                path, headers={**agent, "Idempotency-Key": f"agent-{uuid4().hex}"}, json=payload
            )
            assert denied.status_code == 403, (path, denied.text)
            assert denied.json()["error"]["code"] == "agent_risk_denied", path
        inbox_as_agent = await client.get(
            "/v1/staff/invitation-proposals", headers=agent, params={"status": "pending"}
        )
        assert inbox_as_agent.status_code == 403, inbox_as_agent.text
        assert _invitation_count(e2e_admin_conn, organization_id) == (0, 0)
        assert e2e_admin_conn.execute(
            "SELECT status,revision FROM request_engine.staff_invitation_proposals WHERE id=%s",
            (proposal_id,),
        ).fetchone() == ("pending", 1)

        inbox = await client.get(
            "/v1/staff/invitation-proposals", headers=owner, params={"status": "pending"}
        )
        assert inbox.status_code == 200, inbox.text
        assert [item["proposal_id"] for item in inbox.json()["items"]] == [proposal_id]
        assert inbox.json()["items"][0]["proposed_by_display_name"] == "Chief of Staff"

        approve_headers = {**owner, "Idempotency-Key": f"approve-{uuid4().hex}"}
        approved = await client.post(
            f"/v1/staff/invitation-proposals/{proposal_id}:approve",
            headers=approve_headers,
            json=approve_body,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["decided_by_principal_id"] == str(owner_id)
        invitation_id = approved.json()["invitation_id"]
        invitation = await client.get(f"/v1/staff/invitations/{invitation_id}", headers=owner)
        assert invitation.status_code == 200, invitation.text
        assert invitation.json()["email"] == "maria.lopez@example.test"
        assert invitation.json()["status"] == "pending"
        assert e2e_admin_conn.execute(
            "SELECT invited_by_principal_id FROM request_engine.staff_invitations WHERE id=%s",
            (invitation_id,),
        ).fetchone() == (owner_id,)
        assert _invitation_count(e2e_admin_conn, organization_id) == (1, 1)
        replay = await client.post(
            f"/v1/staff/invitation-proposals/{proposal_id}:approve",
            headers=approve_headers,
            json=approve_body,
        )
        assert replay.status_code == 200 and replay.json() == approved.json()
        assert _invitation_count(e2e_admin_conn, organization_id) == (1, 1)
        assert len(store.staged) == 1

        second = await client.post(
            "/v1/staff/invitation-proposals",
            headers={**agent, "Idempotency-Key": f"voice-{uuid4().hex}"},
            json={"email": "pedro@example.test", "provenance_reference": "owner text request"},
        )
        assert second.status_code == 201, second.text
        rejected = await client.post(
            f"/v1/staff/invitation-proposals/{second.json()['proposal_id']}:reject",
            headers={**owner, "Idempotency-Key": f"reject-{uuid4().hex}"},
            json={
                "expected_revision": 1,
                "reason": "Pedro already left",
                "provenance_reference": "owner rejected",
            },
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["rejection_reason"] == "Pedro already left"
        assert rejected.json()["invitation_id"] is None
        agent_view = await client.get(
            f"/v1/staff/invitation-proposals/{second.json()['proposal_id']}", headers=agent
        )
        assert agent_view.status_code == 200 and agent_view.json()["status"] == "rejected"
        assert _invitation_count(e2e_admin_conn, organization_id) == (1, 1)
        decided = await client.get(
            "/v1/staff/invitation-proposals", headers=owner, params={"status": "pending"}
        )
        assert decided.status_code == 200 and decided.json()["items"] == []
