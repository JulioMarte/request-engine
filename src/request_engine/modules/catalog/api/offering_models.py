from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.catalog.application.queries.search_offerings import OfferingSummary


class OfferingVersionView(BaseModel):
    id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    public_data: dict[str, object]
    amount: Decimal | None = None
    currency: str | None = None


class OfferingView(BaseModel):
    id: UUID
    offering_key: str
    display_name: str
    description: str | None
    latest_version: OfferingVersionView
    eligible_location_ids: tuple[UUID, ...] | None = None

    @classmethod
    def from_contract(cls, offering: OfferingSummary) -> "OfferingView":
        version = offering.latest_version
        return cls(
            id=offering.id,
            offering_key=offering.offering_key,
            display_name=offering.display_name,
            description=offering.description,
            latest_version=OfferingVersionView(
                id=version.id,
                version=version.version,
                duration_minutes=version.duration_minutes,
                bookable=version.bookable,
                requestable=version.requestable,
                public_data=version.public_data,
                amount=version.amount,
                currency=version.currency,
            ),
            eligible_location_ids=offering.eligible_location_ids,
        )
