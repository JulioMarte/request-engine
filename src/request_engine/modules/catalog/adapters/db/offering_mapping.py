from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.catalog.application.queries.search_offerings import (
    OfferingSummary,
    OfferingVersionInfo,
)


def from_row(
    row: RowMapping,
    *,
    f1_available: bool,
    eligible_location_ids: tuple[UUID, ...] | None = None,
) -> OfferingSummary:
    return OfferingSummary(
        id=cast(UUID, row["id"]),
        offering_key=cast(str, row["offering_key"]),
        display_name=cast(str, row["display_name"]),
        description=cast(str | None, row["description"]),
        latest_version=OfferingVersionInfo(
            id=cast(UUID, row["version_id"]),
            version=cast(int, row["version"]),
            duration_minutes=cast(int | None, row["duration_minutes"]),
            bookable=cast(bool, row["bookable"]),
            requestable=cast(bool, row["requestable"]),
            public_data=cast(dict[str, object], row["public_data"]),
            amount=cast(Decimal | None, row["amount"]) if f1_available else None,
            currency=cast(str | None, row["currency"]) if f1_available else None,
        ),
        eligible_location_ids=eligible_location_ids,
    )
