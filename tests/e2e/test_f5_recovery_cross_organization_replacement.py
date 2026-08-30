from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_operational_day_support import configure_projection
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_cross_org_support import (
    BOGUS_OPTION,
    assert_provider_commitment,
    assert_source_disposal,
    replace_external,
    replace_external_body,
    search_provider_option,
    seed_provider_sandbox,
    seed_requester_sandbox,
)
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import seed_incident_for_proposal
from .operational_support import PgConnection, RuntimeCredentialsLike
from .tenant_sandbox import client_with_actors

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.provenance,
    pytest.mark.security,
]


async def test_f5_cross_organization_replacement_saga(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    app_runtime_credentials: RuntimeCredentialsLike,
) -> None:
    requester = seed_requester_sandbox(e2e_admin_conn)
    source = contextualize_recovery_supply(e2e_admin_conn, requester)
    provider, classification_key = seed_provider_sandbox(e2e_admin_conn)
    actors = {requester.token: f5_actor(requester)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, requester)
        _, slots = await book_commitments(client, e2e_admin_conn, requester)
        restrict_contextual_capacity(e2e_admin_conn, requester, source, slots, count=6)
        proposal = await create_proposal(client, requester)
        item = _affected_without_internal_target(proposal)
        reservation_id = UUID(cast(str, item["reservation_id"]))
        incident_id = seed_incident_for_proposal(e2e_admin_conn, requester, proposal)
        rejected = await replace_external(
            client,
            requester,
            incident_id=incident_id,
            body=replace_external_body(proposal, reservation_id, provider, BOGUS_OPTION),
            idempotency_key=f"f5-cross-org-bogus-{uuid4().hex}",
        )
        option = await search_provider_option(
            e2e_admin_conn,
            e2e_session_factory,
            app_runtime_credentials,
            provider,
            classification_key,
        )
        accepted_key = f"f5-cross-org-accept-{uuid4().hex}"
        accepted = await replace_external(
            client,
            requester,
            incident_id=incident_id,
            body=replace_external_body(proposal, reservation_id, provider, option),
            idempotency_key=accepted_key,
        )
        replay = await replace_external(
            client,
            requester,
            incident_id=incident_id,
            body=replace_external_body(proposal, reservation_id, provider, option),
            idempotency_key=accepted_key,
        )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "RECOVERY_TARGET_UNAVAILABLE"
    assert accepted.status_code == 200, accepted.text
    action = accepted.json()
    assert action["status"] == "succeeded"
    assert replay.json()["id"] == action["id"]
    assert replay.json()["owner_steps"] == action["owner_steps"]
    external = UUID(cast(str, action["owner_steps"]["external_commit"]["reservation_id"]))
    assert_provider_commitment(e2e_admin_conn, external, provider)
    assert_source_disposal(e2e_admin_conn, reservation_id)
    rejected_row = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.operational_recovery_actions "
        "WHERE incident_id=%s AND status='rejected' AND failure_code='EXTERNAL_COMMIT_FAILED'",
        (incident_id,),
    ).fetchone()
    assert rejected_row == (1,)


def _affected_without_internal_target(proposal: dict[str, Any]) -> dict[str, Any]:
    items = cast(list[dict[str, Any]], proposal["affected"])
    return next(entry for entry in items if entry["replacement_target"] is None)
