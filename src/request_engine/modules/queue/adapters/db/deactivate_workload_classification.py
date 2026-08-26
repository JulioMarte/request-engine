from typing import cast

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.workload_management_common import (
    record_workload_fact,
    workload_from_json,
    workload_from_row,
    workload_to_json,
)
from request_engine.modules.queue.application.live_commands import (
    DeactivateWorkloadClassificationCommand,
)
from request_engine.modules.queue.application.live_errors import (
    WorkloadClassificationNotFound,
    WorkloadClassificationRevisionConflict,
)
from request_engine.modules.queue.contracts.live_queue import WorkloadClassification
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def deactivate_workload_classification(
    session_factory: SessionFactory,
    command: DeactivateWorkloadClassificationCommand,
) -> WorkloadClassification:
    fingerprint = command_fingerprint(
        "workload.deactivate",
        {"workload_id": command.workload_id, "expected_revision": command.expected_revision},
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="workload.deactivate",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return workload_from_json(cast(dict[str, object], replay["workload"]))
        locked = await session.execute(
            text(
                "SELECT id,workload_key,display_name,active,revision "
                "FROM request_engine.operational_workload_classifications "
                "WHERE organization_id=:organization_id AND id=:workload_id FOR UPDATE"
            ),
            {"organization_id": command.organization_id, "workload_id": command.workload_id},
        )
        row = locked.mappings().one_or_none()
        if row is None:
            raise WorkloadClassificationNotFound(command.workload_id)
        actual_revision = cast(int, row["revision"])
        if actual_revision != command.expected_revision:
            raise WorkloadClassificationRevisionConflict(
                command.workload_id, command.expected_revision, actual_revision
            )
        if not cast(bool, row["active"]):
            result = workload_from_row(row)
        else:
            updated = await session.execute(
                text(
                    "UPDATE request_engine.operational_workload_classifications "
                    "SET active=false,revision=revision+1,updated_at=clock_timestamp() "
                    "WHERE organization_id=:organization_id AND id=:workload_id "
                    "RETURNING id,workload_key,display_name,active,revision"
                ),
                {"organization_id": command.organization_id, "workload_id": command.workload_id},
            )
            result = workload_from_row(updated.mappings().one())
            await record_workload_fact(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_id=idem,
                command_name="workload.deactivate",
                workload=result,
                event_type="workload.classification_deactivated.v1",
            )
        await complete_idempotency(session, idem, {"workload": workload_to_json(result)})
        return result
