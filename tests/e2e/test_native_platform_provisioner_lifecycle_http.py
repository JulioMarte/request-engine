import os
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security, pytest.mark.invariant]


@pytest.mark.asyncio
async def test_platform_provisioner_lifecycle_http_is_revisioned_and_audited(
    e2e_admin_conn: Connection[Any],
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_BOOTSTRAP_DSN",
        make_conninfo(
            host=e2e_admin_conn.info.host,
            port=e2e_admin_conn.info.port,
            dbname=e2e_admin_conn.info.dbname,
            user=e2e_admin_conn.info.user,
            password=os.environ.get("PGPASSWORD", "request_engine"),
        ),
    )
    intent = dict(
        line.split(": ", 1)
        for line in issue_intent(
            ttl_minutes=5,
            provenance="http-platform-provisioner-lifecycle-proof",
        ).splitlines()
    )
    authority_id = UUID(intent["Native authority"])
    root_id = establish_root(
        login_handle="lifecycle-root@example.test",
        password="root lifecycle proof password",
        raw_token=intent["ONE-TIME BOOTSTRAP TOKEN"],
    )
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "lifecycle-root@example.test",
                "password": "root lifecycle proof password",
            },
        )
        assert root_login.status_code == 201
        root_headers = {"Authorization": f"Bearer {root_login.json()['access_token']}"}

        enrollment = await client.post(
            "/auth/native/identities",
            json={
                "login_handle": "lifecycle-provisioner@example.test",
                "password": "lifecycle provisioner proof password",
            },
        )
        assert enrollment.status_code == 201
        created = await client.post(
            "/v1/platform/provisioners",
            headers={**root_headers, "Idempotency-Key": "lifecycle-create-1"},
            json={
                "native_identity_id": enrollment.json()["native_identity_id"],
                "provenance_reference": "deployment:lifecycle-provisioner",
            },
        )
        assert created.status_code == 201, created.text
        provisioner_id = created.json()["principal_id"]

        assert (await client.get("/v1/platform/provisioners")).status_code == 401
        listing = await client.get("/v1/platform/provisioners", headers=root_headers)
        assert listing.status_code == 200
        assert listing.headers["Cache-Control"] == "no-store"
        items = listing.json()["items"]
        assert [item["principal_id"] for item in items] == [provisioner_id]
        assert listing.json()["next_after"] is None
        provisioner = items[0]
        assert provisioner["capabilities"] == ["organization.provision"]
        assert provisioner["binding_status"] == "active"
        assert provisioner["provenance_reference"] == "deployment:lifecycle-provisioner"
        first_revision = provisioner["authority_revision"]

        fetched = await client.get(
            f"/v1/platform/provisioners/{provisioner_id}", headers=root_headers
        )
        assert fetched.status_code == 200
        assert fetched.json() == provisioner
        assert (
            await client.get(f"/v1/platform/provisioners/{root_id}", headers=root_headers)
        ).status_code == 404

        missing_key = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:suspend",
            headers=root_headers,
            json={
                "expected_revision": first_revision,
                "reason_code": "operator_suspension",
            },
        )
        assert missing_key.status_code == 422

        suspend_headers = {**root_headers, "Idempotency-Key": "lifecycle-suspend-1"}
        suspend_body = {
            "expected_revision": first_revision,
            "reason_code": "operator_suspension",
            "external_case_reference": "case-2026-014",
        }
        suspended = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:suspend",
            headers=suspend_headers,
            json=suspend_body,
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["action"] == "suspend"
        assert suspended.json()["binding_status"] == "suspended"
        assert suspended.json()["authority_revision"] == first_revision + 1
        replay = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:suspend",
            headers=suspend_headers,
            json=suspend_body,
        )
        assert replay.status_code == 200
        assert replay.json() == suspended.json()

        key_reuse = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:reactivate",
            headers=suspend_headers,
            json={
                "expected_revision": first_revision + 1,
                "reason_code": "operator_reactivation",
            },
        )
        assert key_reuse.status_code == 409
        assert key_reuse.json()["error"]["code"] == "platform_provisioner_lifecycle_conflict"

        stale = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:reactivate",
            headers={**root_headers, "Idempotency-Key": "lifecycle-stale-1"},
            json={
                "expected_revision": first_revision,
                "reason_code": "operator_reactivation",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "platform_authority_changed"
        assert stale.json()["error"]["resolution"] == "refresh_and_retry"

        suspended_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "lifecycle-provisioner@example.test",
                "password": "lifecycle provisioner proof password",
            },
        )
        assert suspended_login.status_code == 201
        suspended_denied = await client.get(
            "/v1/platform/provisioners",
            headers={"Authorization": f"Bearer {suspended_login.json()['access_token']}"},
        )
        assert suspended_denied.status_code == 403
        assert suspended_denied.json()["error"]["code"] == "identity_binding_suspended"

        reactivated = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:reactivate",
            headers={**root_headers, "Idempotency-Key": "lifecycle-reactivate-1"},
            json={
                "expected_revision": first_revision + 1,
                "reason_code": "investigation_closed",
            },
        )
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()["binding_status"] == "active"
        assert reactivated.json()["authority_revision"] == first_revision + 2

        provisioner_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "lifecycle-provisioner@example.test",
                "password": "lifecycle provisioner proof password",
            },
        )
        assert provisioner_login.status_code == 201
        provisioner_headers = {
            "Authorization": f"Bearer {provisioner_login.json()['access_token']}"
        }
        read_denied = await client.get("/v1/platform/provisioners", headers=provisioner_headers)
        assert read_denied.status_code == 403
        assert read_denied.json()["error"]["code"] == "platform_provisioner_read_forbidden"
        lifecycle_denied = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:suspend",
            headers={**provisioner_headers, "Idempotency-Key": "provisioner-self-suspend"},
            json={
                "expected_revision": first_revision + 2,
                "reason_code": "operator_suspension",
            },
        )
        assert lifecycle_denied.status_code == 403
        assert (
            lifecycle_denied.json()["error"]["code"] == "platform_provisioner_lifecycle_forbidden"
        )

        revoked = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:revoke",
            headers={**root_headers, "Idempotency-Key": "lifecycle-revoke-1"},
            json={
                "expected_revision": first_revision + 2,
                "reason_code": "operator_offboarding",
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["binding_status"] == "revoked"
        assert revoked.json()["authority_revision"] == first_revision + 4
        revoked_replay = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:revoke",
            headers={**root_headers, "Idempotency-Key": "lifecycle-revoke-1"},
            json={
                "expected_revision": first_revision + 2,
                "reason_code": "operator_offboarding",
            },
        )
        assert revoked_replay.status_code == 200
        assert revoked_replay.json() == revoked.json()
        terminal = await client.post(
            f"/v1/platform/provisioners/{provisioner_id}:suspend",
            headers={**root_headers, "Idempotency-Key": "lifecycle-terminal-1"},
            json={
                "expected_revision": first_revision + 4,
                "reason_code": "operator_suspension",
            },
        )
        assert terminal.status_code == 409
        assert terminal.json()["error"]["code"] == "platform_provisioner_lifecycle_conflict"

        revoked_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "lifecycle-provisioner@example.test",
                "password": "lifecycle provisioner proof password",
            },
        )
        assert revoked_login.status_code == 201
        revoked_denied = await client.get(
            "/v1/platform/provisioners",
            headers={"Authorization": f"Bearer {revoked_login.json()['access_token']}"},
        )
        assert revoked_denied.status_code == 403
        assert revoked_denied.json()["error"]["code"] == "identity_binding_revoked"

        final_listing = await client.get("/v1/platform/provisioners", headers=root_headers)
        assert final_listing.status_code == 200
        final_item = final_listing.json()["items"][0]
        assert final_item["binding_status"] == "revoked"
        assert final_item["capabilities"] == []
        assert final_item["authority_revision"] == first_revision + 4

        schema = (await client.get("/openapi.json")).json()
        for path, operation in (
            ("/v1/platform/provisioners", "platform_native_provisioner_list"),
            (
                "/v1/platform/provisioners/{principal_id}",
                "platform_native_provisioner_get",
            ),
            (
                "/v1/platform/provisioners/{principal_id}:suspend",
                "platform_native_provisioner_suspend",
            ),
            (
                "/v1/platform/provisioners/{principal_id}:reactivate",
                "platform_native_provisioner_reactivate",
            ),
            (
                "/v1/platform/provisioners/{principal_id}:revoke",
                "platform_native_provisioner_revoke",
            ),
        ):
            assert (
                schema["paths"][path]["post" if ":" in path else "get"]["operationId"] == operation
            )
            assert (
                schema["paths"][path]["post" if ":" in path else "get"]["x-request-engine-owner"]
                == "tenancy"
            )

    facts = e2e_admin_conn.execute(
        """
        SELECT action, reason_code, revision_before, revision_after,
               external_case_reference, actor_principal_id
          FROM request_engine.platform_authority_lifecycle_facts
         WHERE principal_id = %s ORDER BY created_at, id
        """,
        (provisioner_id,),
    ).fetchall()
    assert [fact[0] for fact in facts] == ["suspend", "reactivate", "revoke"]
    assert facts[0] == (
        "suspend",
        "operator_suspension",
        first_revision,
        first_revision + 1,
        "case-2026-014",
        root_id,
    )
    assert facts[2] == (
        "revoke",
        "operator_offboarding",
        first_revision + 2,
        first_revision + 4,
        None,
        root_id,
    )
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id = %s",
        (UUID(suspended.json()["binding_id"]),),
    ).fetchone() == ("revoked",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.principal_authority_grants WHERE principal_id = %s",
        (provisioner_id,),
    ).fetchall() == [("revoked",)]
