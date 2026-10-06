import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from request_engine.modules.delivery.api.live_models import ResourceActivityView


class ResourceActivityPageView(BaseModel):
    items: list[ResourceActivityView]
    next_cursor: str | None = None


class ResourceActivityCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter_key: str
    started_at: AwareDatetime
    activity_id: UUID


def activity_filter_key(
    organization_id: UUID,
    resource_id: UUID,
    active_only: bool,
    started_after: datetime | None,
    started_before: datetime | None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            (str(organization_id), str(resource_id), active_only, started_after, started_before),
            default=str,
        ).encode()
    ).hexdigest()


def decode_activity_cursor(cursor: str, filter_key: str) -> ResourceActivityCursorParams:
    try:
        value = ResourceActivityCursorParams.model_validate_json(
            base64.b64decode(cursor, altchars=b"-_", validate=True)
        )
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="cursor is invalid") from None
    if value.filter_key != filter_key:
        raise HTTPException(status_code=422, detail="cursor does not match these filters")
    return value


def encode_activity_cursor(value: ResourceActivityCursorParams) -> str:
    return base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()
