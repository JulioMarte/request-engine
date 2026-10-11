"""Real HTTP/PG proof: API creates definitions; retries retain their exact version."""

import asyncio
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.entrypoints.http.app import create_app
from request_engine.modules.requests.adapters.db import definition_management as definition_adapter
from request_engine.modules.requests.adapters.db import request_commands
from request_engine.modules.requests.adapters.db.definition_management import (
    PostgresRequestDefinitionCommands,
)
from request_engine.modules.requests.application.commands.manage_definition import (
    CreateRequestDefinitionCommand,
    RequestDefinitionState,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired


@dataclass(frozen=True)
class AdministrationWorld:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID


def _authority_world(conn: Connection[Any]) -> AdministrationWorld:
    suffix = uuid4().hex
    org = conn.execute(
        "INSERT INTO request_engine.organizations (organization_key,display_name) "
        "VALUES (%s,'Request administration') RETURNING id",
        (suffix,),
    ).fetchone()
    assert org is not None
    principal = conn.execute(
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) VALUES (%s,'agent',%s) RETURNING id",
        (org[0], suffix),
    ).fetchone()
    party = conn.execute(
        "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
        "VALUES (%s,'organization','Definition administrator') RETURNING id",
        (org[0],),
    ).fetchone()
    assert principal is not None and party is not None
    for capability in (
        "requests.create_definition",
        "requests.publish_definition_version",
        "requests.set_definition_active",
        "requests.read_definitions",
        "requests.read_inbox",
    ):
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(organization_id,"
            "principal_id,principal_plane,authority_plane,capability_key,"
            "granted_by_principal_id,provenance_kind,provenance_reference) "
            "VALUES(%s,%s,'tenant','operational',%s,%s,'operator','test administration grant')",
            (org[0], principal[0], capability, principal[0]),
        )
    return AdministrationWorld(cast(UUID, org[0]), cast(UUID, principal[0]), cast(UUID, party[0]))


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.security
@pytest.mark.parametrize("command_first", [True, False])
async def test_definition_creation_serializes_representation_withdrawal_without_partial_effects(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    command_first: bool,
) -> None:
    world = _authority_world(admin_conn)
    admin_conn.execute(
        "INSERT INTO request_engine.representations "
        "(organization_id,principal_id,represented_party_id,scope_key,authority_kind) "
        "VALUES (%s,%s,%s,'operations.manage_profile','delegated')",
        (world.organization_id, world.principal_id, world.authority_party_id),
    )
    command = CreateRequestDefinitionCommand(
        world.organization_id,
        world.principal_id,
        world.authority_party_id,
        "authority-race",
        "Authority race",
        {"type": "object"},
        None,
        uuid4().hex,
    )
    owner = PostgresRequestDefinitionCommands(session_factory)
    ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    release = asyncio.Event()

    async def observe_wait(holder: int) -> None:
        async with asyncio.timeout(10):
            while True:
                row = admin_conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND %s=ANY(pg_blocking_pids(pid)) AND wait_event_type='Lock'",
                    (holder,),
                ).fetchone()
                if row is not None and row[0] > 0:
                    return
                await asyncio.sleep(0.01)

    async def admitted(
        session: AsyncSession, *, organization_id: UUID, principal_id: UUID, capability: str
    ) -> None:
        await require_current_tenant_capability(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            capability=capability,
        )
        ready.set_result((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await asyncio.wait_for(release.wait(), 10)

    async def revoke(session: AsyncSession) -> None:
        await session.execute(
            text(
                "UPDATE request_engine.representations SET status='revoked',revision=revision+1 "
                "WHERE organization_id=:o AND principal_id=:p "
                "AND scope_key='operations.manage_profile'"
            ),
            {"o": world.organization_id, "p": world.principal_id},
        )

    async def withdraw() -> None:
        async with tenant_transaction(session_factory, world.organization_id) as session:
            await revoke(session)

    creating: asyncio.Task[RequestDefinitionState]
    if command_first:
        monkeypatch.setattr(definition_adapter, "require_current_tenant_capability", admitted)
        creating = asyncio.create_task(owner.create_definition(command))
        withdrawing: asyncio.Task[None] | None = None
        try:
            holder = await asyncio.wait_for(ready, 10)
            withdrawing = asyncio.create_task(withdraw())
            await observe_wait(holder)
            assert not withdrawing.done()
        finally:
            release.set()
            try:
                async with asyncio.timeout(10):
                    created = await creating
            finally:
                if withdrawing is not None:
                    await asyncio.wait_for(withdrawing, 10)
        monkeypatch.undo()
        assert created.request_key == "authority-race" and created.version == created.revision == 1
    else:
        async with tenant_transaction(session_factory, world.organization_id) as writer:
            await revoke(writer)
            holder = (await writer.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            creating = asyncio.create_task(owner.create_definition(command))
            await observe_wait(holder)
            assert not creating.done()
        with pytest.raises(OperationalAuthorityRequired):
            async with asyncio.timeout(10):
                await creating
    with pytest.raises(OperationalAuthorityRequired):
        await owner.create_definition(
            command
        )  # Fresh invocation/replay requires current authority.
    expected = 1 if command_first else 0
    for table in (
        "request_definitions",
        "request_definition_versions",
        "idempotency_records",
        "audit_records",
    ):
        assert admin_conn.execute(
            f"SELECT count(*) FROM request_engine.{table} WHERE organization_id=%s",
            (world.organization_id,),
        ).fetchone() == (expected,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id=%s",
        (world.organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.integration
async def test_definition_api_versioning_inbox_and_retry_after_deactivation(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
) -> None:
    world = _authority_world(admin_conn)
    grants = frozenset(
        {
            "requests.create_definition",
            "requests.publish_definition_version",
            "requests.set_definition_active",
            "requests.read_definitions",
            "requests.read_inbox",
            "requests.submit",
            "organization.bootstrap",
        }
    )

    class Resolver:
        async def resolve_actor(self, request: Request) -> ActorContext:
            return ActorContext(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                capabilities=grants if request.headers.get("Authorization") else frozenset(),
            )

    app = create_app(session_factory=session_factory, actor_resolver=Resolver())
    headers = {"Authorization": "fixture-explicit-grant", "Idempotency-Key": uuid4().hex}
    body = {
        "authority_party_id": str(world.authority_party_id),
        "request_key": "contact",
        "display_name": "Contact",
        "input_schema": {"type": "object"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post(
            "/v1/request-definitions", json=body, headers={"Idempotency-Key": uuid4().hex}
        )
        assert denied.status_code == 403
        authority = await client.post(
            "/v1/organization/bootstrap-operational-authority",
            headers=headers,
            json={"authority_party_id": str(world.authority_party_id)},
        )
        assert authority.status_code == 200, authority.text
        for bad_key in (
            "../contact",
            "with space",
            "contact/child",
            "question?",
            "fragment#",
            "..",
        ):
            invalid_key = await client.post(
                "/v1/request-definitions",
                headers=headers,
                json={**body, "request_key": bad_key},
            )
            assert invalid_key.status_code == 422
        invalid = await client.post(
            "/v1/request-definitions",
            json={**body, "input_schema": {"properties": []}},
            headers=headers,
        )
        assert (
            invalid.status_code == 422
            and invalid.json()["error"]["code"] == "request_payload_invalid"
        )
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.request_definitions"
        ).fetchone() == (0,)
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.idempotency_records "
            "WHERE capability LIKE 'requests.%'"
        ).fetchone() == (0,)
        created = await client.post("/v1/request-definitions", json=body, headers=headers)
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["version"] == first["revision"] == 1
        definition_id = first["definition_id"]
        submitted_body = {"definition_version": 1, "payload": {"message": "hello"}}
        submit_headers = {**headers, "Idempotency-Key": uuid4().hex}
        submit_url = "/v1/requests/definitions/contact/submit"
        missing_version = await client.post(
            submit_url, json={"payload": {}}, headers=submit_headers
        )
        assert missing_version.status_code == 422
        submitted = await client.post(submit_url, json=submitted_body, headers=submit_headers)
        assert submitted.status_code == 201, submitted.text
        published = await client.post(
            f"/v1/request-definitions/{definition_id}/versions",
            headers=headers,
            json={
                "authority_party_id": str(world.authority_party_id),
                "expected_revision": 1,
                "input_schema": {
                    "type": "object",
                    "required": ["new_field"],
                    "properties": {"new_field": {"type": "boolean"}},
                },
            },
        )
        assert published.status_code == 201, published.text
        assert published.json()["version"] == published.json()["revision"] == 2
        stale = await client.post(
            f"/v1/request-definitions/{definition_id}:set-active",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={
                "authority_party_id": str(world.authority_party_id),
                "expected_revision": 1,
                "active": False,
            },
        )
        assert stale.status_code == 409
        disabled = await client.post(
            f"/v1/request-definitions/{definition_id}:set-active",
            headers=headers,
            json={
                "authority_party_id": str(world.authority_party_id),
                "expected_revision": 2,
                "active": False,
            },
        )
        assert disabled.status_code == 200, disabled.text
        replay = await client.post(submit_url, json=submitted_body, headers=submit_headers)
        assert replay.status_code == 201 and replay.json() == submitted.json()
        fresh = await client.post(
            submit_url, json=submitted_body, headers={**headers, "Idempotency-Key": uuid4().hex}
        )
        assert (
            fresh.status_code == 409
            and fresh.json()["error"]["code"] == "request_definition_inactive"
        )
        schema = await client.get(
            f"/v1/request-definitions/{definition_id}?version=1", headers=headers
        )
        assert schema.status_code == 200 and schema.json()["version_id"] == first["version_id"]
        inbox = await client.get("/v1/requests?status=open&limit=1", headers=headers)
        assert inbox.status_code == 200, inbox.text
        assert len(inbox.json()["items"]) == 1 and inbox.json()["next_cursor"] is None
        assert "payload" not in inbox.json()["items"][0]
        item = inbox.json()["items"][0]
        assert item["request_id"] == submitted.json()["request"]["id"]
        assert item["definition_id"] == definition_id
        assert item["request_key"] == "contact"
        assert item["definition_version"] == 1
        assert item["definition_version_id"] == first["version_id"]
        historical = await client.get(
            f"/v1/request-definitions/{item['definition_id']}",
            params={"version": item["definition_version"]},
            headers=headers,
        )
        assert historical.status_code == 200, historical.text
        assert historical.json()["input_schema"] == {"type": "object"}
        latest = await client.get(f"/v1/request-definitions/{definition_id}", headers=headers)
        assert latest.status_code == 200, latest.text
        assert latest.json()["version"] == 2
        assert latest.json()["input_schema"]["required"] == ["new_field"]
        assert inbox.headers["Cache-Control"] == "no-store"
        second_definition = await client.post(
            "/v1/request-definitions",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={**body, "request_key": "callback"},
        )
        assert second_definition.status_code == 201, second_definition.text
        first_page = await client.get("/v1/request-definitions?limit=1", headers=headers)
        assert first_page.status_code == 200, first_page.text
        assert len(first_page.json()["items"]) == 1 and first_page.json()["next_cursor"]
        second_page = await client.get(
            "/v1/request-definitions",
            headers=headers,
            params={"limit": 1, "cursor": first_page.json()["next_cursor"]},
        )
        assert second_page.status_code == 200 and second_page.json()["next_cursor"] is None
        actual_ids = {
            page.json()["items"][0]["definition_id"] for page in (first_page, second_page)
        }
        assert actual_ids == {definition_id, second_definition.json()["definition_id"]}
        missing = await client.get(f"/v1/request-definitions/{uuid4()}", headers=headers)
        assert missing.status_code == 404
        admin_conn.execute(
            "UPDATE request_engine.principal_authority_grants SET status='revoked',"
            "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
            "WHERE principal_id=%s AND capability_key='requests.create_definition'",
            (world.principal_id, world.principal_id),
        )
        # The resolver still advertises the old grant. Even the completed receipt
        # must not survive current standing-capability withdrawal.
        withdrawn_replay = await client.post("/v1/request-definitions", json=body, headers=headers)
        assert withdrawn_replay.status_code == 403, withdrawn_replay.text
        assert withdrawn_replay.json()["error"]["code"] == "capability_required"
        admin_conn.execute(
            "UPDATE request_engine.representations SET status='revoked' "
            "WHERE organization_id=%s AND scope_key='operations.manage_profile'",
            (world.organization_id,),
        )
        revoked = await client.post(
            f"/v1/request-definitions/{definition_id}/versions",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={
                "authority_party_id": str(world.authority_party_id),
                "expected_revision": disabled.json()["revision"],
                "input_schema": {"type": "object"},
            },
        )
        assert revoked.status_code == 403, revoked.text
    assert admin_conn.execute("SELECT count(*) FROM request_engine.requests").fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.request_definition_versions "
        "WHERE request_definition_id=%s",
        (definition_id,),
    ).fetchone() == (2,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.idempotency_records WHERE capability='requests.submit'"
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.request_definitions"
    ).fetchone() == (2,)


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.integration
async def test_fresh_submission_serializes_definition_deactivation_without_lost_demand(
    admin_conn: Connection[Any],
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _authority_world(admin_conn)

    class Resolver:
        async def resolve_actor(self, request: Request) -> ActorContext:
            return ActorContext(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                capabilities=frozenset(
                    {
                        "requests.create_definition",
                        "requests.set_definition_active",
                        "requests.submit",
                        "organization.bootstrap",
                    }
                ),
            )

    app = create_app(session_factory=session_factory, actor_resolver=Resolver())
    headers = {"Idempotency-Key": uuid4().hex}
    locked, release = asyncio.Event(), asyncio.Event()
    real_load = request_commands.load_request_definition_version

    async def pause_after_real_lock(*args: Any, **kwargs: Any) -> Any:
        result = await real_load(*args, **kwargs)
        if kwargs.get("lock_definition"):
            locked.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        return result

    monkeypatch.setattr(request_commands, "load_request_definition_version", pause_after_real_lock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        authority = await client.post(
            "/v1/organization/bootstrap-operational-authority",
            headers=headers,
            json={"authority_party_id": str(world.authority_party_id)},
        )
        assert authority.status_code == 200, authority.text
        created = await client.post(
            "/v1/request-definitions",
            headers=headers,
            json={
                "authority_party_id": str(world.authority_party_id),
                "request_key": "race",
                "display_name": "Race",
                "input_schema": {"type": "object"},
            },
        )
        assert created.status_code == 201, created.text
        definition_id = created.json()["definition_id"]
        submit = asyncio.create_task(
            client.post(
                "/v1/requests/definitions/race/submit",
                headers=headers,
                json={"definition_version": 1, "payload": {}},
            )
        )
        deactivate: asyncio.Task[Any] | None = None
        try:
            await asyncio.wait_for(locked.wait(), timeout=10)
            deactivate = asyncio.create_task(
                client.post(
                    f"/v1/request-definitions/{definition_id}:set-active",
                    headers=headers,
                    json={
                        "authority_party_id": str(world.authority_party_id),
                        "expected_revision": 1,
                        "active": False,
                    },
                )
            )
            async with asyncio.timeout(10):
                while True:
                    blocked = admin_conn.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND wait_event_type='Lock' "
                        "AND query LIKE '%%SELECT revision FROM "
                        "request_engine.request_definitions%%' "
                        "AND cardinality(pg_blocking_pids(pid))>0"
                    ).fetchone()
                    if blocked is not None and blocked[0] > 0:
                        break
                    await asyncio.sleep(0.01)
            assert not deactivate.done(), "deactivation bypassed the definition serialization root"
        finally:
            release.set()
            submitted = await submit
            disabled = await deactivate if deactivate is not None else None
        assert submitted.status_code == 201, submitted.text
        assert disabled is not None and disabled.status_code == 200, disabled
        fresh = await client.post(
            "/v1/requests/definitions/race/submit",
            headers={"Idempotency-Key": uuid4().hex},
            json={"definition_version": 1, "payload": {}},
        )
        assert fresh.status_code == 409
    assert admin_conn.execute("SELECT count(*) FROM request_engine.requests").fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.idempotency_records WHERE capability='requests.submit'"
    ).fetchone() == (1,)
