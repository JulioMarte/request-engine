"""A delegated business administrator can configure; revocation denies the next request.

Protected guarantee: INV-STAFF-REPRESENTATION-001 (plus INV-AUTHORITY-001). The
plausible defects this proof catches: configuration still requiring the root
controller, delegated rows becoming re-delegable, the operation stripping the
controller's root Representation, revocation not reaching the next transaction,
and missing/duplicated audit or receipt replay. The app runs through the real
native HTTP stack on a restricted ``request_engine_app`` login; database rows are
read with the admin connection only as an independent oracle (plus one explicit
fixture grant that establishes a second plausible manager).
"""

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"staff-representation-e2e-signing-key-v1"
_PROFILE = "operations.manage_profile"
_SUPPLY = "operations.manage_supply"


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _provision_tenant_root(
    conn: PgConnection, *, identity_authority_id: UUID, native_identity_id: UUID
) -> tuple[UUID, UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (principal_plane, principal_kind, external_subject)
        VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"staff-rep-platform-{uuid4().hex}",),
    )
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (%s, 'platform', 'platform', 'organization.provision', false,
                  'trust_bootstrap', %s)
        """,
        (provisioner_id, f"staff-rep-root:{uuid4().hex}"),
    )
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (provisioner_id,),
    ).fetchone()
    assert revision is not None
    organization_id, party_id, controller_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(int(revision[0])),),
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            # The current fresh-organization policy: the owner holds exactly the
            # grants and root Representations a real clinic owner holds.
            conn.execute(
                "SELECT request_platform.select_initial_controller_policy(%s)",
                ("tenant-controller-v10",),
            )
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    organization_id,
                    f"staff-rep-{organization_id.hex}",
                    "Staff Representation E2E",
                    party_id,
                    controller_id,
                    identity_authority_id,
                    native_identity_id,
                    f"staff-rep-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    for setting in ("authenticated_principal_id", "authority_revision"):
        conn.execute("SELECT set_config(%s, '', false)", (f"request_engine.{setting}",))
    return organization_id, party_id, controller_id


def _headers(token: str, organization_id: UUID, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-RE-Organization-ID": str(organization_id)}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def _login(client: AsyncClient, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions", json={"login_handle": login_handle, "password": password}
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


async def _activate_member(
    client: AsyncClient,
    root_token: str,
    organization_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> UUID:
    invited = await client.post(
        "/v1/staff/members/native",
        headers=_headers(root_token, organization_id, f"invite-{uuid4().hex}"),
        json={
            "identity_authority_id": str(authority_id),
            "native_identity_id": str(native_identity_id),
            "provenance_reference": "staff-rep-e2e-invite",
        },
    )
    assert invited.status_code == 201, invited.text
    membership_id = UUID(invited.json()["membership_id"])
    activated = await client.put(
        f"/v1/staff/members/{membership_id}/status",
        headers=_headers(root_token, organization_id, f"activate-{uuid4().hex}"),
        json={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": "staff-rep-e2e-activate",
        },
    )
    assert activated.status_code == 200, activated.text
    return membership_id


async def _authority_revision(
    client: AsyncClient, token: str, organization_id: UUID, membership_id: UUID
) -> int:
    detail = await client.get(
        f"/v1/staff/members/{membership_id}", headers=_headers(token, organization_id)
    )
    assert detail.status_code == 200, detail.text
    return int(detail.json()["authority_revision"])


async def _replace_scopes(
    client: AsyncClient,
    token: str,
    organization_id: UUID,
    membership_id: UUID,
    party_id: UUID,
    *,
    expected_revision: int,
    scopes: list[str],
    key: str | None = None,
) -> Response:
    return await client.put(
        f"/v1/staff/members/{membership_id}/representations/{party_id}",
        headers=_headers(token, organization_id, key or f"rep-{uuid4().hex}"),
        json={
            "expected_authority_revision": expected_revision,
            "desired_scopes": scopes,
            "provenance_reference": "staff-rep-e2e-delegation",
        },
    )


async def _update_profile(
    client: AsyncClient, token: str, organization_id: UUID, party_id: UUID, name: str
) -> Response:
    return await client.patch(
        "/v1/operations/organization/profile",
        headers=_headers(token, organization_id, f"profile-{uuid4().hex}"),
        json={"authority_party_id": str(party_id), "legal_name": name},
    )


async def _read_resources(
    client: AsyncClient, token: str, organization_id: UUID, party_id: UUID
) -> Response:
    return await client.get(
        "/v1/booking/resources",
        headers=_headers(token, organization_id),
        params={"authority_party_id": str(party_id)},
    )


def _active_rows(conn: PgConnection, principal_id: UUID, party_id: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT scope_key, delegable, granted_by_principal_id
          FROM request_engine.representations
         WHERE principal_id = %s AND represented_party_id = %s AND status = 'active'
         ORDER BY scope_key
        """,
        (principal_id, party_id),
    ).fetchall()


@pytest.mark.asyncio
async def test_delegated_admin_configures_and_revocation_is_immediate(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _uuid_row(
        e2e_admin_conn,
        "INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment) "
        "VALUES ('native', %s) RETURNING id",
        (f"staff-rep-e2e-{uuid4().hex}",),
    )
    runtime = build_native_auth_runtime(e2e_session_factory)
    passwords = {name: f"{name}-staff-rep-password-1" for name in ("root", "admin", "third")}
    identities = {
        name: await runtime.service.enroll_password_identity(
            identity_authority_id=authority_id,
            login_handle=f"{name}-{uuid4().hex}@example.test",
            password=password,
        )
        for name, password in passwords.items()
    }
    organization_id, party_id, root_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=identities["root"].native_identity_id,
    )
    foreign_org, foreign_party, _ = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=identities["third"].native_identity_id,
    )
    del foreign_org

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root = await _login(client, identities["root"].login_handle, passwords["root"])
        admin_membership = await _activate_member(
            client, root, organization_id, authority_id, identities["admin"].native_identity_id
        )
        third_membership = await _activate_member(
            client, root, organization_id, authority_id, identities["third"].native_identity_id
        )
        admin_id = _uuid_row(
            e2e_admin_conn,
            "SELECT principal_id FROM request_engine.staff_memberships WHERE id = %s",
            (admin_membership,),
        )
        root_membership = _uuid_row(
            e2e_admin_conn,
            "SELECT id FROM request_engine.staff_memberships WHERE principal_id = %s",
            (root_id,),
        )
        granted = await client.put(
            f"/v1/staff/members/{admin_membership}/authority",
            headers=_headers(root, organization_id, f"authority-{uuid4().hex}"),
            json={
                "expected_authority_revision": await _authority_revision(
                    client, root, organization_id, admin_membership
                ),
                "desired_capabilities": ["booking.read_supply", "organization.manage_profile"],
                "provenance_reference": "staff-rep-e2e-capabilities",
            },
        )
        assert granted.status_code == 200, granted.text
        admin = await _login(client, identities["admin"].login_handle, passwords["admin"])

        # The capability alone is not enough: the business Party scope is missing.
        denied_profile = await _update_profile(client, admin, organization_id, party_id, "A")
        assert denied_profile.status_code == 403, denied_profile.text
        assert denied_profile.json()["error"]["code"] == "operational_authority_required"
        denied_read = await _read_resources(client, admin, organization_id, party_id)
        assert denied_read.status_code == 403, denied_read.text

        listed = await client.get(
            f"/v1/staff/members/{root_membership}/representations",
            headers=_headers(root, organization_id),
        )
        assert listed.status_code == 200, listed.text
        assert {
            (item["scope_key"], item["delegable"]) for item in listed.json()["representations"]
        } == {
            (scope, True)
            for scope in (
                _PROFILE,
                _SUPPLY,
                "operations.manage_terms",
                "operations.manage_discovery",
            )
        }

        # Stale revision and self-delegation are refused without effect.
        current_revision = await _authority_revision(
            client, root, organization_id, admin_membership
        )
        stale = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            party_id,
            expected_revision=current_revision - 1,
            scopes=[_PROFILE],
        )
        assert stale.status_code == 409, stale.text
        self_target = await _replace_scopes(
            client,
            root,
            organization_id,
            root_membership,
            party_id,
            expected_revision=await _authority_revision(
                client, root, organization_id, root_membership
            ),
            scopes=[_PROFILE],
        )
        assert self_target.status_code == 403, self_target.text
        foreign = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            foreign_party,
            expected_revision=current_revision,
            scopes=[_PROFILE],
        )
        assert foreign.status_code == 404, foreign.text
        unknown = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            party_id,
            expected_revision=current_revision,
            scopes=["staff.invite"],
        )
        assert unknown.status_code == 422, unknown.text
        assert _active_rows(e2e_admin_conn, admin_id, party_id) == []

        # Delegate profile + supply; the receipt replays exactly.
        key = f"delegate-{uuid4().hex}"
        delegated = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            party_id,
            expected_revision=current_revision,
            scopes=[_SUPPLY, _PROFILE],
            key=key,
        )
        assert delegated.status_code == 200, delegated.text
        body = delegated.json()
        assert body["scopes"] == body["added"] == [_PROFILE, _SUPPLY]
        assert body["removed"] == []
        assert body["authority_revision"] > current_revision
        replay = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            party_id,
            expected_revision=current_revision,
            scopes=[_SUPPLY, _PROFILE],
            key=key,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == body
        assert _active_rows(e2e_admin_conn, admin_id, party_id) == [
            (_PROFILE, False, root_id),
            (_SUPPLY, False, root_id),
        ]

        configured = await _update_profile(client, admin, organization_id, party_id, "Clinic SA")
        assert configured.status_code == 200, configured.text
        supply = await _read_resources(client, admin, organization_id, party_id)
        assert supply.status_code == 200, supply.text

        # A second manager holding only delegated (non-delegable) rows cannot
        # re-delegate and cannot strip the controller's root Representation.
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT %s, %s, 'tenant', 'tenant_control', capability_key, false, %s,
                   'authority_management', 'staff-rep-e2e-fixture-manager'
              FROM (VALUES ('staff.manage_authority'), ('staff.read')) AS caps(capability_key)
            """,
            (organization_id, admin_id, root_id),
        )
        admin = await _login(client, identities["admin"].login_handle, passwords["admin"])
        redelegate = await _replace_scopes(
            client,
            admin,
            organization_id,
            third_membership,
            party_id,
            expected_revision=await _authority_revision(
                client, admin, organization_id, third_membership
            ),
            scopes=[_PROFILE],
        )
        assert redelegate.status_code == 403, redelegate.text
        strip_root = await _replace_scopes(
            client,
            admin,
            organization_id,
            root_membership,
            party_id,
            expected_revision=await _authority_revision(
                client, admin, organization_id, root_membership
            ),
            scopes=[],
        )
        assert strip_root.status_code == 200, strip_root.text
        assert strip_root.json()["removed"] == []
        assert len(strip_root.json()["scopes"]) == 4
        assert len(_active_rows(e2e_admin_conn, root_id, party_id)) == 4

        # Revocation by the owner is effective on the admin's very next request.
        revoked = await _replace_scopes(
            client,
            root,
            organization_id,
            admin_membership,
            party_id,
            expected_revision=await _authority_revision(
                client, root, organization_id, admin_membership
            ),
            scopes=[],
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["removed"] == [_PROFILE, _SUPPLY]
        assert revoked.json()["scopes"] == []
        after_profile = await _update_profile(client, admin, organization_id, party_id, "B")
        assert after_profile.status_code == 403, after_profile.text
        assert after_profile.json()["error"]["code"] == "operational_authority_required"
        after_read = await _read_resources(client, admin, organization_id, party_id)
        assert after_read.status_code == 403, after_read.text
        still_root = await _update_profile(client, root, organization_id, party_id, "Owner")
        assert still_root.status_code == 200, still_root.text

        revoked_rows = e2e_admin_conn.execute(
            """
            SELECT count(*), bool_and(revoked_by_principal_id = %s AND revoked_at IS NOT NULL)
              FROM request_engine.representations
             WHERE principal_id = %s AND status = 'revoked'
            """,
            (root_id, admin_id),
        ).fetchone()
        assert revoked_rows == (2, True)
        audit = e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.audit_records
             WHERE organization_id = %s AND command_name = 'staff.manage_authority'
               AND details->>'action' = 'representation_replace'
            """,
            (organization_id,),
        ).fetchone()
        # delegate, strip-root no-op, revoke; the replay and refusals add nothing.
        assert audit == (3,)
