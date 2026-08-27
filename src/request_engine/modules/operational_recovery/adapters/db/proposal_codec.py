from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.operational_recovery.adapters.db.affected_codec import (
    affected_from_json,
)
from request_engine.modules.operational_recovery.adapters.db.checkpoint_codec import (
    checkpoint_from_json,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


def proposal_from_row(row: RowMapping) -> RescheduleProposal:
    raw = cast(dict[str, object], row["snapshot"])
    affected = cast(list[dict[str, object]], raw["affected"])
    checkpoint = cast(dict[str, object], raw["source_checkpoint"])
    return RescheduleProposal(
        id=cast(UUID, row["id"]),
        service_queue_id=cast(UUID, row["service_queue_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        observed_at=cast(datetime, row["observed_at"]),
        horizon_end=cast(datetime, row["horizon_end"]),
        source_fingerprint=cast(str, row["source_fingerprint"]),
        source_checkpoint=checkpoint_from_json(checkpoint),
        proposal_fingerprint=cast(str, row["proposal_fingerprint"]),
        executable_capacity_seconds=cast(int, row["executable_capacity_seconds"]),
        committed_capacity_seconds=cast(int, row["committed_capacity_seconds"]),
        shortfall_seconds=cast(int, row["shortfall_seconds"]),
        affected=tuple(affected_from_json(item) for item in affected),
        created_at=cast(datetime, row["created_at"]),
    )


def with_created_at(
    proposal: RescheduleProposal,
    created_at: datetime,
) -> RescheduleProposal:
    return RescheduleProposal(
        id=proposal.id,
        service_queue_id=proposal.service_queue_id,
        resource_id=proposal.resource_id,
        location_id=proposal.location_id,
        observed_at=proposal.observed_at,
        horizon_end=proposal.horizon_end,
        source_fingerprint=proposal.source_fingerprint,
        source_checkpoint=proposal.source_checkpoint,
        proposal_fingerprint=proposal.proposal_fingerprint,
        executable_capacity_seconds=proposal.executable_capacity_seconds,
        committed_capacity_seconds=proposal.committed_capacity_seconds,
        shortfall_seconds=proposal.shortfall_seconds,
        affected=proposal.affected,
        created_at=created_at,
    )
