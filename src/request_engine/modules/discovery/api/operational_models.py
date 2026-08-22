from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OfferingClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    classification_key: str = Field(min_length=1, max_length=120)
    expected_revision: int | None = Field(default=None, ge=1)


class DiscoveryPublicationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None = None
    effective_start: datetime
    effective_end: datetime | None = None
    provider_visibility: Literal["hidden", "public"] = "hidden"


class RevokeDiscoveryPublicationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    expected_revision: int = Field(ge=1)
