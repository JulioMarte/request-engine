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
from request_engine.modules.live_capacity.application.errors import (
    InvalidProjectionConfiguration,
)
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_projection_scope_update_rejects_foreign_reference_without_revision_change(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    local = create_live_ops_fixture(admin_conn)
    foreign = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, local.organization_id)
    policy = await create_projection_scope(
        command_session_factory,
        CreateProjectionScopeCommand(
            organization_id=local.organization_id,
            principal_id=principal_id,
            service_queue_id=local.queue_id,
            resource_id=local.resource_id,
            location_id=local.location_id,
            idempotency_key=f"f4-create-{uuid4().hex}",
        ),
    )

    with pytest.raises(InvalidProjectionConfiguration):
        await update_projection_scope(
            command_session_factory,
            UpdateProjectionScopeCommand(
                organization_id=local.organization_id,
                principal_id=principal_id,
                policy_id=policy.id,
                resource_id=foreign.resource_id,
                location_id=local.location_id,
                active=True,
                expected_revision=policy.revision,
                idempotency_key=f"f4-update-invalid-{uuid4().hex}",
            ),
        )

    row = admin_conn.execute(
        "SELECT resource_id,location_id,active,revision "
        "FROM request_engine.live_capacity_projection_policies "
        "WHERE organization_id=%s AND id=%s",
        (local.organization_id, policy.id),
    ).fetchone()
    assert row == (local.resource_id, local.location_id, True, policy.revision)
    audit_count = admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='live_capacity.configure_scope'",
        (local.organization_id,),
    ).fetchone()
    assert audit_count == (1,)
