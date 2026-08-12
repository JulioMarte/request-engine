from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.catalog.application.queries.get_business_info import BusinessInfo
from request_engine.modules.catalog.application.queries.search_offerings import OfferingSummary


class BusinessLocationView(BaseModel):
    id: UUID
    location_key: str
    display_name: str
    timezone: str
    public_data: dict[str, object]


class BusinessInfoView(BaseModel):
    organization_id: UUID
    organization_key: str
    display_name: str
    public_profile: dict[str, object]
    locations: tuple[BusinessLocationView, ...]

    @classmethod
    def from_contract(cls, info: BusinessInfo) -> "BusinessInfoView":
        return cls(
            organization_id=info.organization_id,
            organization_key=info.organization_key,
            display_name=info.display_name,
            public_profile=info.public_profile,
            locations=tuple(
                BusinessLocationView(
                    id=item.id,
                    location_key=item.location_key,
                    display_name=item.display_name,
                    timezone=item.timezone,
                    public_data=item.public_data,
                )
                for item in info.locations
            ),
        )


class OfferingVersionView(BaseModel):
    id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    public_data: dict[str, object]


class OfferingView(BaseModel):
    id: UUID
    offering_key: str
    display_name: str
    description: str | None
    latest_version: OfferingVersionView

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
            ),
        )
