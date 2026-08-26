from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.live_capacity.adapters.db.policy_common import (
    policy_to_json,
    projection_scope_from_json,
    projection_scope_from_row,
    record_policy_fact,
)
from request_engine.modules.live_capacity.adapters.db.projection_scope_validation import (
    validate_projection_scope,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    UpdateProjectionScopeCommand,
)
from request_engine.modules.live_capacity.application.errors import (
    PolicyRevisionConflict,
    ProjectionPolicyNotFound,
)
from request_engine.modules.live_capacity.contracts.policy import ProjectionScopePolicy
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def update_projection_scope(
    session_factory: SessionFactory, command: UpdateProjectionScopeCommand
) -> ProjectionScopePolicy:
    payload = {
        "policy_id": str(command.policy_id),
        "resource_id": str(command.resource_id),
        "location_id": str(command.location_id),
        "active": command.active,
        "expected_revision": command.expected_revision,
    }
    fingerprint = command_fingerprint("live_capacity.configure_scope", payload)
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="live_capacity.configure_scope",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return projection_scope_from_json(cast(dict[str, object], replay["policy"]))
        service_queue_id = await session.scalar(
            text(
                "SELECT service_queue_id FROM request_engine.live_capacity_projection_policies "
                "WHERE organization_id=:organization_id AND id=:policy_id"
            ),
            {"organization_id": command.organization_id, "policy_id": command.policy_id},
        )
        if service_queue_id is None:
            raise ProjectionPolicyNotFound(command.policy_id)
        await validate_projection_scope(
            session,
            organization_id=command.organization_id,
            service_queue_id=cast(UUID, service_queue_id),
            resource_id=command.resource_id,
            location_id=command.location_id,
        )
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE request_engine.live_capacity_projection_policies "
                        "SET resource_id=:resource_id,location_id=:location_id,active=:active,"
                        "revision=revision+1 WHERE organization_id=:organization_id "
                        "AND id=:policy_id AND revision=:expected_revision "
                        "RETURNING id,service_queue_id,resource_id,location_id,active,revision"
                    ),
                    {"organization_id": command.organization_id, **payload},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise PolicyRevisionConflict(command.expected_revision)
        policy = projection_scope_from_row(row)
        await record_policy_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="live_capacity.configure_scope",
            policy=policy,
            event_type="live_capacity.projection_scope_updated.v1",
        )
        await complete_idempotency(session, idem, {"policy": policy_to_json(policy)})
        return policy
