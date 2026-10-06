from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from request_engine.modules.requests.application.commands.manage_definition import (
    validate_definition_key,
)
from request_engine.modules.requests.application.errors import RequestPayloadInvalid


class DefinitionSchemasBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None = None


class CreateRequestDefinitionBody(DefinitionSchemasBody):
    authority_party_id: UUID
    request_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("request_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        try:
            validate_definition_key(value)
        except RequestPayloadInvalid as exc:
            raise ValueError(exc.reason) from None
        return value


class PublishRequestDefinitionVersionBody(DefinitionSchemasBody):
    authority_party_id: UUID
    expected_revision: int = Field(ge=1)


class SetRequestDefinitionActiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    expected_revision: int = Field(ge=1)
    active: bool


class RequestDefinitionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    definition_id: UUID
    request_key: str
    display_name: str
    active: bool
    revision: int
    version_id: UUID
    version: int
    input_schema: dict[str, object]
    result_schema: dict[str, object] | None


class RequestDefinitionPageView(BaseModel):
    items: tuple[RequestDefinitionView, ...]
    next_cursor: str | None = None


class RequestInboxItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    request_id: UUID
    definition_version_id: UUID
    definition_id: UUID
    request_key: str
    definition_version: int
    requester_party_id: UUID | None
    recipient_party_id: UUID | None
    status: Literal["open", "completed", "cancelled", "failed"]
    revision: int
    created_at: datetime


class RequestInboxPageView(BaseModel):
    items: tuple[RequestInboxItemView, ...]
    next_cursor: str | None = None
