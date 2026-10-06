import base64
import hashlib
import json
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


class OfferingCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter_key: str
    display_name: str = Field(max_length=200)
    offering_id: UUID
    effective_at: AwareDatetime | None = None


def offering_filter_key(filters: tuple[object, ...]) -> str:
    return hashlib.sha256(json.dumps(filters, default=str).encode()).hexdigest()


def decode_offering_cursor(cursor: str, filter_key: str) -> OfferingCursorParams:
    try:
        value = OfferingCursorParams.model_validate_json(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
    except (ValueError, ValidationError):
        raise CatalogInvalidInput("cursor is invalid") from None
    if value.filter_key != filter_key:
        raise CatalogInvalidInput("cursor does not match these filters")
    return value


def encode_offering_cursor(value: OfferingCursorParams) -> str:
    return base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()
