from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ResourceCapabilityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    capability_id: UUID
    capability_key: str
    display_name: str


class OfferingBootstrapView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    offering_id: UUID
    offering_version_id: UUID
    offering_key: str
    version: int
    requirement_ids: tuple[UUID, ...]
