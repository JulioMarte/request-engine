import asyncio
from uuid import uuid4

import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection
from f4_customer_projection_fixture import create_principal

from request_engine.modules.live_capacity.adapters.db.create_projection_policy import (
    create_projection_scope,
)
from request_engine.modules.live_capacity.adapters.db.update_projection_policy import (
    update_projection_scope,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    CreateProjectionScopeCommand,
    UpdateProjectionScopeCommand,
)
from request_engine.modules.live_capacity.application.errors import PolicyRevisionConflict
from request_engine.modules.live_capacity.contracts.policy import ProjectionScopePolicy
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.concurrency
@pytest.mark.provenance
async def test_projection_scope_revision_race_has_one_winner_and_one_conflict(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    fixture = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, fixture.organization_id)
    policy = await create_projection_scope(
        command_session_factory,
        CreateProjectionScopeCommand(
            organization_id=fixture.organization_id,
            principal_id=principal_id,
            service_queue_id=fixture.queue_id,
            resource_id=fixture.resource_id,
            location_id=fixture.location_id,
            idempotency_key=f"f4-race-create-{uuid4().hex}",
        ),
    )

    async def update(active: bool) -> ProjectionScopePolicy | Exception:
        try:
            return await update_projection_scope(
                command_session_factory,
                UpdateProjectionScopeCommand(
                    organization_id=fixture.organization_id,
                    principal_id=principal_id,
                    policy_id=policy.id,
                    resource_id=fixture.resource_id,
                    location_id=fixture.location_id,
                    active=active,
                    expected_revision=policy.revision,
                    idempotency_key=f"f4-race-update-{active}-{uuid4().hex}",
                ),
            )
        except Exception as exc:
            return exc

    results = await asyncio.gather(update(False), update(True))
    winners = [result for result in results if isinstance(result, ProjectionScopePolicy)]
    losers = [result for result in results if isinstance(result, PolicyRevisionConflict)]
    assert len(winners) == 1
    assert len(losers) == 1
    winner = winners[0]
    assert winner.revision == policy.revision + 1

    row = admin_conn.execute(
        "SELECT active,revision FROM request_engine.live_capacity_projection_policies "
        "WHERE organization_id=%s AND id=%s",
        (fixture.organization_id, policy.id),
    ).fetchone()
    assert row == (winner.active, winner.revision)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='live_capacity.configure_scope'",
        (fixture.organization_id,),
    ).fetchone() == (2,)
