from collections.abc import Collection
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.domain.delivery_policy import (
    DeliveryPolicy,
    DeliveryRoute,
    resolve_provider_key,
)
from request_engine.modules.communications.domain.errors import (
    DeliveryConfigurationError,
    RecipientChannelUnavailable,
)


async def resolve_dispatch_route_and_contact_point(
    session: AsyncSession,
    *,
    organization_id: UUID,
    task: RowMapping,
    policy: DeliveryPolicy,
    configured_provider_keys: Collection[str],
) -> tuple[DeliveryRoute, str, RowMapping]:
    explicit_id = cast(UUID | None, task["contact_point_id"])
    if explicit_id is not None:
        point = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, channel, normalized_value
                        FROM request_engine.party_contact_points
                        WHERE organization_id = :organization_id
                          AND id = :contact_point_id
                          AND party_id = :recipient_party_id
                          AND active
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "contact_point_id": explicit_id,
                        "recipient_party_id": task["recipient_party_id"],
                    },
                )
            )
            .mappings()
            .first()
        )
        if point is None:
            raise RecipientChannelUnavailable("pinned contact point is no longer usable")
        point_channel = cast(str, point["channel"])
        route = next(
            (route for route in policy.routes if route.endpoint_channel == point_channel),
            None,
        )
        if route is None:
            raise DeliveryConfigurationError(
                "explicit contact point does not match channel_policy.channels"
            )
        return route, resolve_provider_key(route.provider_key, configured_provider_keys), point

    points = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, channel, normalized_value
                    FROM request_engine.party_contact_points
                    WHERE organization_id = :organization_id
                      AND party_id = :recipient_party_id
                      AND active
                      AND verified
                    ORDER BY created_at, id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "recipient_party_id": task["recipient_party_id"],
                },
            )
        )
        .mappings()
        .all()
    )
    for route in policy.routes:
        point = next(
            (
                candidate
                for candidate in points
                if cast(str, candidate["channel"]) == route.endpoint_channel
            ),
            None,
        )
        if point is not None:
            return route, resolve_provider_key(route.provider_key, configured_provider_keys), point
    raise DeliveryConfigurationError("recipient has no usable verified contact point")
