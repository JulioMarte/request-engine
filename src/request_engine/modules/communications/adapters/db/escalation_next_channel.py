"""Next-channel and guard reads for the escalation step (docs/v3/36 section 4).

A channel with no active+verified contact point for the recipient counts as
exhausted (``recipient_unreachable`` is "all contact points for the current
channel exhausted"), so the walk skips it instead of creating a child that
could never dispatch. NOTE: when two policy channels share an endpoint
channel (sms/voice both map to phone) the pinned point resolves to the first
policy route for that endpoint at dispatch time; voice has no transport in
the baseline, so current policies are unaffected.
"""

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.domain.delivery_policy import (
    DeliveryPolicy,
)
from request_engine.modules.communications.domain.escalation_policy import (
    remaining_escalation_channels,
)


async def resolve_next_channel_contact_point(
    session: AsyncSession,
    *,
    organization_id: UUID,
    recipient_party_id: UUID,
    policy: DeliveryPolicy,
    attempted_channels: set[str],
    after_channel: str | None,
) -> tuple[str, RowMapping] | None:
    """First policy channel after the last attempted one, with a usable point."""

    candidates = set(
        remaining_escalation_channels(
            tuple(route.channel for route in policy.routes),
            attempted_channels,
            after_channel,
        )
    )
    for route in policy.routes:
        if route.channel not in candidates:
            continue
        point = (
            (
                await session.execute(
                    text(
                        "SELECT id, normalized_value"
                        " FROM request_engine.party_contact_points"
                        " WHERE organization_id = :organization_id"
                        " AND party_id = :recipient_party_id"
                        " AND channel = :endpoint_channel"
                        " AND active AND verified"
                        " ORDER BY created_at, id LIMIT 1"
                    ),
                    {
                        "organization_id": organization_id,
                        "recipient_party_id": recipient_party_id,
                        "endpoint_channel": route.endpoint_channel,
                    },
                )
            )
            .mappings()
            .first()
        )
        if point is not None:
            return route.channel, point
    return None


def child_expires_at(parent: RowMapping, policy: DeliveryPolicy, db_now: datetime) -> datetime:
    """One workable delivery window for a child of a deadline-missed lineage.

    The deadline is lineage-wide, but a child created after the parent
    deadline still gets ``max(parent.expires_at, db_now + max(retry_after,
    reconcile) seconds)`` — reaching the patient after a missed deadline is
    the point of the ``delivery_deadline_missed`` trigger.
    """

    window = timedelta(seconds=max(policy.retry_after_seconds, policy.reconcile_after_seconds))
    parent_expires = cast(datetime | None, parent["expires_at"])
    if parent_expires is None:
        return db_now + window
    return max(parent_expires, db_now + window)


async def database_now(session: AsyncSession) -> datetime:
    return cast(
        datetime,
        (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
    )


async def today_contact_count(
    session: AsyncSession,
    *,
    organization_id: UUID,
    recipient_party_id: UUID,
) -> int:
    """Outbound contact intents created for the party on the database day.

    Interpretation of the docs/v3/36 section 4 fatigue guard: a created
    CommunicationTask is one durable outbound contact intent, counted across
    all lineages and purposes for the recipient party.
    """

    return cast(
        int,
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM request_engine.communication_tasks"
                    " WHERE organization_id = :organization_id"
                    " AND recipient_party_id = :recipient_party_id"
                    " AND created_at::date = clock_timestamp()::date"
                ),
                {
                    "organization_id": organization_id,
                    "recipient_party_id": recipient_party_id,
                },
            )
        ).scalar_one(),
    )
