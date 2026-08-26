from uuid import uuid4

import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection
from f4_customer_projection_fixture import create_principal, uuid_row

from request_engine.modules.live_capacity.adapters.db.create_projection_policy import (
    create_projection_scope,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    CreateProjectionScopeCommand,
)
from request_engine.modules.live_capacity.application.errors import (
    InvalidProjectionConfiguration,
)
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_projection_scope_rejects_foreign_resource_without_partial_effects(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    local = create_live_ops_fixture(admin_conn)
    foreign = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, local.organization_id)

    with pytest.raises(InvalidProjectionConfiguration):
        await create_projection_scope(
            command_session_factory,
            CreateProjectionScopeCommand(
                organization_id=local.organization_id,
                principal_id=principal_id,
                service_queue_id=local.queue_id,
                resource_id=foreign.resource_id,
                location_id=local.location_id,
                idempotency_key=f"f4-invalid-{uuid4().hex}",
            ),
        )

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.live_capacity_projection_policies "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (local.organization_id, local.queue_id),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='live_capacity.configure_scope'",
        (local.organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_projection_scope_rejects_queue_location_mismatch_and_accepts_valid_scope(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    fixture = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, fixture.organization_id)
    other_location_id = uuid_row(
        admin_conn,
        "INSERT INTO request_engine.locations "
        "(organization_id,location_key,display_name,timezone) "
        "VALUES (%s,%s,'Other Location','UTC') RETURNING id",
        (fixture.organization_id, f"other-{uuid4().hex}"),
    )

    with pytest.raises(InvalidProjectionConfiguration):
        await create_projection_scope(
            command_session_factory,
            CreateProjectionScopeCommand(
                organization_id=fixture.organization_id,
                principal_id=principal_id,
                service_queue_id=fixture.queue_id,
                resource_id=fixture.resource_id,
                location_id=other_location_id,
                idempotency_key=f"f4-mismatch-{uuid4().hex}",
            ),
        )

    policy = await create_projection_scope(
        command_session_factory,
        CreateProjectionScopeCommand(
            organization_id=fixture.organization_id,
            principal_id=principal_id,
            service_queue_id=fixture.queue_id,
            resource_id=fixture.resource_id,
            location_id=fixture.location_id,
            idempotency_key=f"f4-valid-{uuid4().hex}",
        ),
    )
    assert policy.service_queue_id == fixture.queue_id
    assert policy.resource_id == fixture.resource_id
    assert policy.location_id == fixture.location_id
