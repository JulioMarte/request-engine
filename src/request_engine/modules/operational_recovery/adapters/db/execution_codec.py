from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.operational_recovery.adapters.db.target_codec import target_from_json
from request_engine.modules.operational_recovery.contracts.models import OperationalNotification, RecoveryExecution, RecoveryExecutionStatus


def execution_from_row(row: RowMapping) -> RecoveryExecution:
    return RecoveryExecution(
        id=cast(UUID, row["id"]),
        proposal_id=cast(UUID, row["proposal_id"]),
        reservation_id=cast(UUID, row["reservation_id"]),
        status=RecoveryExecutionStatus(cast(str, row["status"])),
        original_reservation_revision=cast(int, row["original_reservation_revision"]),
        resulting_reservation_revision=cast(int | None, row["resulting_reservation_revision"]),
        target=target_from_json(cast(dict[str, object], row["target"])),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        failure_code=cast(str | None, row["failure_code"]),
        notification=OperationalNotification(requested=cast(bool, row["notification_requested"]), communication_task_id=cast(UUID | None, row["communication_task_id"])),
    )
