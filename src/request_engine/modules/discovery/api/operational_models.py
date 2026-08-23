from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OfferingClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    authority_party_id: UUID
    classification_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
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

    @model_validator(mode="after")
    def validate_interval(self) -> "DiscoveryPublicationBody":
        if self.effective_start.utcoffset() is None:
            raise ValueError("effective_start must be timezone-aware")
        if self.effective_end is not None:
            if self.effective_end.utcoffset() is None:
                raise ValueError("effective_end must be timezone-aware")
            if self.effective_end <= self.effective_start:
                raise ValueError("effective_end must be after effective_start")
        return self


class RevokeDiscoveryConfigurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_party_id: UUID
    expected_revision: int = Field(ge=1)
