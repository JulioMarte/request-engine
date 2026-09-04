"""Read-side of the organization channel-policy table.

Resolution precedence for one task: the task's frozen channel_policy snapshot
wins unless it is exactly the hardcoded patient-transactional default sentinel
(task-level policy absent); only then the organization policy for the task's
purpose applies, and only while it is enabled. A missing row and a disabled
purpose both fall back to the frozen default for tasks already in flight.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.domain.delivery_policy import (
    DeliveryPolicy,
    is_patient_transactional_default,
    parse_delivery_policy,
)
from request_engine.modules.communications.domain.errors import ChannelPurposeDisabled


async def read_purpose_row(
    session: AsyncSession,
    *,
    organization_id: UUID,
    purpose: str,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT enabled, channel_policy
                    FROM request_engine.organization_channel_policies
                    WHERE organization_id = :organization_id
                      AND purpose = :purpose
                    """
                ),
                {"organization_id": organization_id, "purpose": purpose},
            )
        )
        .mappings()
        .first()
    )


async def ensure_purpose_enabled(
    session: AsyncSession,
    *,
    organization_id: UUID,
    purpose: str,
) -> None:
    """Reject creation of a new intent for an intentionally disabled purpose."""

    row = await read_purpose_row(session, organization_id=organization_id, purpose=purpose)
    if row is not None and row["enabled"] is not True:
        raise ChannelPurposeDisabled(purpose)


async def resolve_task_delivery_policy(
    session: AsyncSession,
    *,
    organization_id: UUID,
    task: RowMapping,
) -> DeliveryPolicy:
    frozen = cast(dict[str, object], task["channel_policy"])
    purpose = cast(str, task["purpose"])
    if is_patient_transactional_default(frozen):
        row = await read_purpose_row(session, organization_id=organization_id, purpose=purpose)
        if row is not None and row["enabled"] is True:
            return parse_delivery_policy(cast(dict[str, object], row["channel_policy"]))
    return parse_delivery_policy(frozen)


async def count_disabled_purposes(
    session: AsyncSession,
    *,
    organization_id: UUID,
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM request_engine.organization_channel_policies
                    WHERE organization_id = :organization_id
                      AND enabled = false
                    """
                ),
                {"organization_id": organization_id},
            )
        ).scalar_one(),
    )
