from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OfferingVersionInfo:
    id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    public_data: dict[str, object]
    amount: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class OfferingSummary:
    id: UUID
    offering_key: str
    display_name: str
    description: str | None
    latest_version: OfferingVersionInfo
    eligible_location_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchOfferingsQuery:
    organization_id: UUID
    search_text: str | None = None
    bookable: bool | None = None
    requestable: bool | None = None
    location_id: UUID | None = None
    effective_at: datetime | None = None
    limit: int = 50


class OfferingCatalogReader(Protocol):
    async def search_offerings(
        self,
        query: SearchOfferingsQuery,
    ) -> tuple[OfferingSummary, ...]: ...

    async def get_offering_by_key(
        self,
        organization_id: UUID,
        offering_key: str,
    ) -> OfferingSummary | None: ...


async def search_offerings(
    reader: OfferingCatalogReader,
    query: SearchOfferingsQuery,
) -> tuple[OfferingSummary, ...]:
    if query.limit <= 0 or query.limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if query.search_text is not None and len(query.search_text) > 200:
        raise ValueError("search_text must be at most 200 characters")
    if query.effective_at is not None and (
        query.effective_at.tzinfo is None or query.effective_at.utcoffset() is None
    ):
        raise ValueError("effective_at must be timezone-aware")
    return await reader.search_offerings(query)


async def get_offering_details(
    reader: OfferingCatalogReader,
    *,
    organization_id: UUID,
    offering_key: str,
) -> OfferingSummary | None:
    if not offering_key:
        raise ValueError("offering_key is required")
    return await reader.get_offering_by_key(organization_id, offering_key)
