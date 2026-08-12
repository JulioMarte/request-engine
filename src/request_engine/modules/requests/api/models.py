from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from request_engine.modules.requests.contracts.request import Request


class RequestParticipantInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party_id: UUID
    role_key: str = Field(min_length=1, max_length=120)


class ExternalCorrelationInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correlation_kind: str = Field(min_length=1, max_length=120)
    provider_key: str = Field(min_length=1, max_length=120)
    external_key: str = Field(min_length=1, max_length=500)


class SubmitRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition_version: int | None = Field(default=None, gt=0)
    payload: dict[str, object]
    requester_party_id: UUID | None = None
    recipient_party_id: UUID | None = None
    participants: tuple[RequestParticipantInputModel, ...] = ()
    correlations: tuple[ExternalCorrelationInputModel, ...] = ()

    @model_validator(mode="after")
    def reject_duplicate_children(self) -> "SubmitRequestBody":
        participant_keys = [(item.party_id, item.role_key) for item in self.participants]
        if len(set(participant_keys)) != len(participant_keys):
            raise ValueError("participants must be unique by party_id and role_key")
        correlation_keys = [
            (item.correlation_kind, item.provider_key, item.external_key)
            for item in self.correlations
        ]
        if len(set(correlation_keys)) != len(correlation_keys):
            raise ValueError(
                "correlations must be unique by correlation_kind, provider_key and external_key"
            )
        return self


class RecordRequestResultBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_payload: dict[str, object]
    expected_revision: int | None = Field(default=None, gt=0)


class CompleteRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_payload: dict[str, object] | None = None
    expected_revision: int | None = Field(default=None, gt=0)


class CancelRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=1000)
    expected_revision: int | None = Field(default=None, gt=0)


class FailRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error_class: str = Field(min_length=1, max_length=200)
    details: dict[str, object] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, gt=0)


class RequestParticipantView(BaseModel):
    party_id: UUID
    role_key: str


class ExternalCorrelationView(BaseModel):
    id: UUID
    correlation_kind: str
    provider_key: str
    external_key: str


class RequestView(BaseModel):
    id: UUID
    request_definition_version_id: UUID
    requester_party_id: UUID | None
    recipient_party_id: UUID | None
    status: str
    payload: dict[str, object]
    result_payload: dict[str, object] | None
    revision: int
    created_at: datetime
    completed_at: datetime | None
    updated_at: datetime
    participants: tuple[RequestParticipantView, ...]
    correlations: tuple[ExternalCorrelationView, ...]

    @classmethod
    def from_contract(cls, request: Request) -> "RequestView":
        return cls(
            id=request.id,
            request_definition_version_id=request.request_definition_version_id,
            requester_party_id=request.requester_party_id,
            recipient_party_id=request.recipient_party_id,
            status=request.status.value,
            payload=request.payload,
            result_payload=request.result_payload,
            revision=request.revision,
            created_at=request.created_at,
            completed_at=request.completed_at,
            updated_at=request.updated_at,
            participants=tuple(
                RequestParticipantView(party_id=item.party_id, role_key=item.role_key)
                for item in request.participants
            ),
            correlations=tuple(
                ExternalCorrelationView(
                    id=item.id,
                    correlation_kind=item.correlation_kind,
                    provider_key=item.provider_key,
                    external_key=item.external_key,
                )
                for item in request.correlations
            ),
        )


class SubmittedRequestView(BaseModel):
    request_key: str
    definition_version: int
    request: RequestView
