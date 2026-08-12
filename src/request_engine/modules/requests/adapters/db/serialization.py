from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.requests.contracts.request import (
    ExternalCorrelation,
    Request,
    RequestParticipant,
    RequestStatus,
)


def request_to_json(request: Request) -> dict[str, object]:
    return {
        "id": str(request.id),
        "request_definition_version_id": str(request.request_definition_version_id),
        "requester_party_id": (
            str(request.requester_party_id) if request.requester_party_id else None
        ),
        "recipient_party_id": (
            str(request.recipient_party_id) if request.recipient_party_id else None
        ),
        "status": request.status.value,
        "payload": request.payload,
        "result_payload": request.result_payload,
        "revision": request.revision,
        "created_at": request.created_at.isoformat(),
        "completed_at": request.completed_at.isoformat() if request.completed_at else None,
        "updated_at": request.updated_at.isoformat(),
        "participants": [
            {"party_id": str(item.party_id), "role_key": item.role_key}
            for item in request.participants
        ],
        "correlations": [
            {
                "id": str(item.id),
                "correlation_kind": item.correlation_kind,
                "provider_key": item.provider_key,
                "external_key": item.external_key,
            }
            for item in request.correlations
        ],
    }


def request_from_json(data: dict[str, object]) -> Request:
    requester_raw = cast(str | None, data["requester_party_id"])
    recipient_raw = cast(str | None, data["recipient_party_id"])
    completed_raw = cast(str | None, data["completed_at"])
    participant_values = cast(list[object], data["participants"])
    correlation_values = cast(list[object], data["correlations"])
    return Request(
        id=UUID(cast(str, data["id"])),
        request_definition_version_id=UUID(cast(str, data["request_definition_version_id"])),
        requester_party_id=UUID(requester_raw) if requester_raw else None,
        recipient_party_id=UUID(recipient_raw) if recipient_raw else None,
        status=RequestStatus(cast(str, data["status"])),
        payload=cast(dict[str, object], data["payload"]),
        result_payload=cast(dict[str, object] | None, data["result_payload"]),
        revision=cast(int, data["revision"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
        completed_at=datetime.fromisoformat(completed_raw) if completed_raw else None,
        updated_at=datetime.fromisoformat(cast(str, data["updated_at"])),
        participants=tuple(_participant_from_json(item) for item in participant_values),
        correlations=tuple(_correlation_from_json(item) for item in correlation_values),
    )


def _participant_from_json(value: object) -> RequestParticipant:
    if not isinstance(value, dict):
        raise ValueError("serialized Request participant must be an object")
    data = cast(dict[str, object], value)
    return RequestParticipant(
        party_id=UUID(cast(str, data["party_id"])),
        role_key=cast(str, data["role_key"]),
    )


def _correlation_from_json(value: object) -> ExternalCorrelation:
    if not isinstance(value, dict):
        raise ValueError("serialized Request correlation must be an object")
    data = cast(dict[str, object], value)
    return ExternalCorrelation(
        id=UUID(cast(str, data["id"])),
        correlation_kind=cast(str, data["correlation_kind"]),
        provider_key=cast(str, data["provider_key"]),
        external_key=cast(str, data["external_key"]),
    )
