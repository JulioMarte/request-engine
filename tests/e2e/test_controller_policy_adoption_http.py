"""Dual-consent legacy controller-policy adoption through owner HTTP APIs."""

from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from sqlalchemy import text

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.api.controller_policy_adoption_routes import (
    add_controller_policy_adoption_error_handlers,
    add_controller_policy_adoption_platform_routes,
    add_controller_policy_adoption_tenant_routes,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionInvalid,
    RequestControllerPolicyAdoption,
    WithdrawControllerPolicyAdoption,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]
_SIGNING_KEY = b"controller-policy-adoption-e2e-signing-key-v1"


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _scalar(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> object:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _integer(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> int:
    return int(cast(int, _scalar(conn, query, params)))


def _create_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"adoption-{uuid4().hex}",),
    )


def _provision_legacy_root(
    conn: PgConnection, authority_id: UUID, native_identity_id: UUID, policy: str
) -> tuple[UUID, UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner_id, f"adoption-provisioner:{uuid4().hex}"),
    )
    revision = _integer(
        conn,
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (provisioner_id,),
    )
    organization_id, organization_party_id, root_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)", (str(revision),)
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute("SELECT request_platform.select_initial_controller_policy(%s)", (policy,))
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"legacy-{organization_id.hex}",
                    "Legacy adoption e2e",
                    organization_party_id,
                    root_id,
                    authority_id,
                    native_identity_id,
                    f"adoption-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    binding_id = _uuid_row(
        conn,
        "SELECT controller_binding_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (organization_id,),
    )
    return organization_id, root_id, binding_id


def _platform_owner(
    conn: PgConnection, authority_id: UUID, native_identity_id: UUID
) -> tuple[UUID, UUID, int]:
    principal_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"adoption-owner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,'platform',%s,%s,'active')",
        (principal_id, authority_id, str(native_identity_id)),
    )
    for capability in (
        "platform.organization.adopt_initial_controller_policy",
        "platform.organization.read",
    ):
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,provenance_kind,"
            "provenance_reference) VALUES (%s,'platform','platform',%s,false,"
            "'trust_bootstrap',%s)",
            (principal_id, capability, f"adoption-owner:{uuid4().hex}"),
        )
    binding_id = _uuid_row(
        conn,
        "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s",
        (principal_id,),
    )
    revision = _integer(
        conn,
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (principal_id,),
    )
    return principal_id, binding_id, int(revision)


def _actor_pair(
    conn: PgConnection,
    organization_id: UUID,
    root_id: UUID,
    root_binding_id: UUID,
    platform_id: UUID,
    platform_binding_id: UUID,
    platform_revision: int,
) -> tuple[ActorContext, PlatformActorContext]:
    root_revision = _integer(
        conn,
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (root_id,),
    )
    root_caps = frozenset(
        str(row[0])
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active'",
            (organization_id, root_id),
        ).fetchall()
    )
    now = datetime.now(UTC)
    tenant = ActorContext(
        organization_id=organization_id,
        principal_id=root_id,
        capabilities=root_caps,
        authority_revision=root_revision,
        identity_binding_id=root_binding_id,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    platform = PlatformActorContext(
        principal_id=platform_id,
        capabilities=frozenset(
            {"platform.organization.adopt_initial_controller_policy", "platform.organization.read"}
        ),
        authority_revision=platform_revision,
        identity_binding_id=platform_binding_id,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    return tenant, platform


@pytest.mark.parametrize(
    "source_policy",
    [
        "tenant-controller-v1",
        "tenant-controller-v2",
        "tenant-controller-v3",
        "tenant-controller-v4",
        "tenant-controller-v5",
    ],
)
@pytest.mark.asyncio
async def test_legacy_policy_adoption_http_journey_and_readiness(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    source_policy: str,
) -> None:
    authority_id = _create_authority(e2e_admin_conn)
    enrollment = build_native_auth_runtime(e2e_session_factory)
    root_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"legacy-root-{uuid4().hex}@example.test",
        password="legacy-root-adoption-password-1",
    )
    platform_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"adoption-owner-{uuid4().hex}@example.test",
        password="platform-adoption-password-2",
    )
    organization_id, root_id, root_binding = _provision_legacy_root(
        e2e_admin_conn, authority_id, root_identity.native_identity_id, source_policy
    )
    platform_id, platform_binding, platform_revision = _platform_owner(
        e2e_admin_conn, authority_id, platform_identity.native_identity_id
    )
    root_actor, platform_ctx = _actor_pair(
        e2e_admin_conn,
        organization_id,
        root_id,
        root_binding,
        platform_id,
        platform_binding,
        platform_revision,
    )
    root_revision = cast(int, root_actor.authority_revision)
    root_actor_holder = [root_actor]
    commands = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    reader = PostgresControllerPolicyAdoptionCommands(platform_read_session_factory)
    tenant_app = FastAPI()
    add_controller_policy_adoption_error_handlers(tenant_app)
    tenant_router = APIRouter()

    async def tenant_actor(_: Request) -> ActorContext:
        return root_actor_holder[0]

    add_controller_policy_adoption_tenant_routes(
        tenant_router, commands=commands, authenticated_actor=tenant_actor
    )
    tenant_app.include_router(tenant_router)
    platform_app = FastAPI()
    add_controller_policy_adoption_error_handlers(platform_app)
    platform_router = APIRouter()

    async def authenticated_platform_actor(_: Request) -> PlatformActorContext:
        return platform_ctx

    add_controller_policy_adoption_platform_routes(
        platform_router,
        commands=commands,
        reader=reader,
        authenticated_actor=authenticated_platform_actor,
    )
    platform_app.include_router(platform_router)

    async with (
        AsyncClient(transport=ASGITransport(app=tenant_app), base_url="http://tenant") as tenant,
        AsyncClient(
            transport=ASGITransport(app=platform_app), base_url="http://platform"
        ) as platform,
    ):
        invalid_create = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers={"Idempotency-Key": "   "},
            json={"expected_authority_revision": root_revision, "reason": "legacy policy adoption"},
        )
        assert invalid_create.status_code == 422, invalid_create.text
        assert invalid_create.json()["error"]["code"] == "controller_policy_adoption_invalid"

        with pytest.raises(ControllerPolicyAdoptionInvalid):
            await commands.request_adoption(
                root_actor,
                RequestControllerPolicyAdoption(
                    expected_authority_revision=root_revision,
                    reason="legacy policy adoption",
                    idempotency_key="   ",
                ),
            )

        headers = {"Idempotency-Key": f"consent-{uuid4().hex}"}
        consent = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers=headers,
            json={"expected_authority_revision": root_revision, "reason": "legacy policy adoption"},
        )
        assert consent.status_code == 201, consent.text
        request_id = consent.json()["request_id"]
        request_revision = consent.json()["request_revision"]
        assert consent.headers["cache-control"] == "no-store"

        detail = await tenant.get(f"/v1/controller-policy-adoptions/{request_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "pending"
        assert detail.json()["added_capabilities"] == []

        invalid_withdraw = await tenant.post(
            f"/v1/controller-policy-adoptions/{request_id}:withdraw",
            headers={"Idempotency-Key": "   "},
            json={"expected_request_revision": request_revision},
        )
        assert invalid_withdraw.status_code == 422, invalid_withdraw.text
        assert invalid_withdraw.json()["error"]["code"] == "controller_policy_adoption_invalid"
        with pytest.raises(ControllerPolicyAdoptionInvalid):
            await commands.withdraw_adoption(
                root_actor,
                WithdrawControllerPolicyAdoption(
                    request_id=UUID(request_id),
                    expected_request_revision=request_revision,
                    idempotency_key="   ",
                ),
            )

        invalid_apply = await platform.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={"Idempotency-Key": "   "},
            json={"expected_request_revision": request_revision},
        )
        assert invalid_apply.status_code == 422, invalid_apply.text
        assert invalid_apply.json()["error"]["code"] == "controller_policy_adoption_invalid"
        with pytest.raises(ControllerPolicyAdoptionInvalid):
            await commands.apply_adoption(
                platform_ctx,
                ApplyControllerPolicyAdoption(
                    request_id=UUID(request_id),
                    expected_request_revision=request_revision,
                    idempotency_key="   ",
                ),
            )

        # Advance the persisted consent's valid creation window as a test
        # precondition while preserving its 24-hour shape. GET and exact replay
        # must agree on the effective state without changing or renewing it.
        e2e_admin_conn.execute(
            "UPDATE request_engine.controller_policy_adoption_requests "
            "SET created_at=clock_timestamp()-interval '26 hours', "
            "    expires_at=clock_timestamp()-interval '3 hours' WHERE id=%s",
            (request_id,),
        )
        persisted_expiry = e2e_admin_conn.execute(
            "SELECT status,expires_at FROM request_engine.controller_policy_adoption_requests "
            "WHERE id=%s",
            (request_id,),
        ).fetchone()
        assert persisted_expiry is not None and persisted_expiry[0] == "pending"
        expired_detail = await tenant.get(f"/v1/controller-policy-adoptions/{request_id}")
        assert expired_detail.status_code == 200, expired_detail.text
        assert expired_detail.json()["status"] == "expired"

        expired_replay = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers=headers,
            json={"expected_authority_revision": root_revision, "reason": "legacy policy adoption"},
        )
        assert expired_replay.status_code == 201, expired_replay.text
        assert expired_replay.json()["request_id"] == request_id
        assert expired_replay.json()["status"] == "expired"
        detail_expiry = datetime.fromisoformat(
            expired_detail.json()["expires_at"].replace("Z", "+00:00")
        )
        replay_expiry = datetime.fromisoformat(
            expired_replay.json()["expires_at"].replace("Z", "+00:00")
        )
        assert detail_expiry == replay_expiry == persisted_expiry[1]
        assert (
            e2e_admin_conn.execute(
                "SELECT status,expires_at FROM request_engine.controller_policy_adoption_requests "
                "WHERE id=%s",
                (request_id,),
            ).fetchone()
            == persisted_expiry
        )

        expired_apply = await platform.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={"Idempotency-Key": f"expired-apply-{uuid4().hex}"},
            json={"expected_request_revision": request_revision},
        )
        assert expired_apply.status_code == 409, expired_apply.text
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request_id,),
        ).fetchone() == (0,)

        headers = {"Idempotency-Key": f"consent-after-expiry-{uuid4().hex}"}
        renewed_consent = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers=headers,
            json={"expected_authority_revision": root_revision, "reason": "legacy policy adoption"},
        )
        assert renewed_consent.status_code == 201, renewed_consent.text
        assert renewed_consent.json()["status"] == "pending"
        old_status = e2e_admin_conn.execute(
            "SELECT status FROM request_engine.controller_policy_adoption_requests WHERE id=%s",
            (request_id,),
        ).fetchone()
        assert old_status == ("expired",)
        request_id = renewed_consent.json()["request_id"]
        request_revision = renewed_consent.json()["request_revision"]

        still_pending = await tenant.get(f"/v1/controller-policy-adoptions/{request_id}")
        assert still_pending.status_code == 200
        assert still_pending.json()["status"] == "pending"

        pending = await platform.get("/v1/platform/controller-policy-adoptions?limit=10")
        assert pending.status_code == 200, pending.text
        assert [item["request_id"] for item in pending.json()["items"]] == [request_id]
        assert "reason" not in pending.json()["items"][0]

        applied = await platform.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={"Idempotency-Key": f"apply-{uuid4().hex}"},
            json={"expected_request_revision": request_revision},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["platform_approver_principal_id"] == str(platform_id)
        assert applied.json()["target_policy_key"] == "tenant-controller-v6"
        assert applied.json()["added_capabilities"]
        assert applied.json()["authority_revision_after"] > root_revision

        grant_rows = e2e_admin_conn.execute(
            "SELECT capability_key,granted_by_principal_id FROM "
            "request_engine.principal_authority_grants WHERE organization_id=%s "
            "AND principal_id=%s AND provenance_reference=%s ORDER BY capability_key",
            (organization_id, root_id, f"adoption:{request_id}"),
        ).fetchall()
        assert [str(row[0]) for row in grant_rows] == applied.json()["added_capabilities"]
        assert all(row[1] == platform_id for row in grant_rows)

        # Replaying consent uses fresh current actor state but the original body/key.
        new_root = _actor_pair(
            e2e_admin_conn,
            organization_id,
            root_id,
            root_binding,
            platform_id,
            platform_binding,
            platform_revision,
        )[0]
        root_actor_holder[0] = new_root
        consent_replay = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers=headers,
            json={"expected_authority_revision": root_revision, "reason": "legacy policy adoption"},
        )
        assert consent_replay.status_code == 201, consent_replay.text
        assert consent_replay.json()["request_id"] == request_id
        assert consent_replay.json()["status"] == "applied"

        final_detail = await tenant.get(f"/v1/controller-policy-adoptions/{request_id}")
        assert final_detail.status_code == 200, final_detail.text
        assert final_detail.json()["status"] == "applied"
        assert final_detail.json()["authority_revision_before"] == root_revision
        assert (
            final_detail.json()["authority_revision_after"]
            == applied.json()["authority_revision_after"]
        )
        assert final_detail.json()["added_capabilities"] == applied.json()["added_capabilities"]

        async with actor_transaction(e2e_session_factory, new_root) as session:
            readiness = await session.scalar(
                text("SELECT request_engine.read_onboarding_identity_facts(:organization_id)"),
                {"organization_id": organization_id},
            )
        assert readiness["tenant_control"]["recorded_policy_key"] == "tenant-controller-v6"
        assert readiness["tenant_control"]["current_policy_ready"] is True
        assert (
            readiness["controller_authority_revision"] == applied.json()["authority_revision_after"]
        )

        no_longer_pending = await platform.get("/v1/platform/controller-policy-adoptions")
        assert no_longer_pending.status_code == 200, no_longer_pending.text
        assert no_longer_pending.json()["items"] == []
