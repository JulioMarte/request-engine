from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext


@dataclass(frozen=True, slots=True)
class RequestControllerPolicyAdoption:
    expected_authority_revision: int
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class WithdrawControllerPolicyAdoption:
    request_id: UUID
    expected_request_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ApplyControllerPolicyAdoption:
    request_id: UUID
    expected_request_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ListControllerPolicyAdoptions:
    after: UUID | None = None
    limit: int = 50
    request_id: UUID | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 101:
            raise ValueError("limit must be between 1 and 101")


@dataclass(frozen=True, slots=True)
class ControllerPolicyAdoptionSummary:
    request_id: UUID
    organization_id: UUID
    controller_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    expected_authority_revision: int
    status: str
    request_revision: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ControllerPolicyAdoptionReview:
    request: ControllerPolicyAdoptionSummary
    reason: str
    current_authority_revision: int
    proposed_capabilities: tuple[str, ...]
    revoked_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ControllerPolicyAdoptionDetail(ControllerPolicyAdoptionSummary):
    authority_revision_before: int | None = None
    authority_revision_after: int | None = None
    added_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ControllerPolicyAdoptionRequestResult:
    request_id: UUID
    source_policy_key: str
    target_policy_key: str
    authority_revision: int
    request_revision: int
    status: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ControllerPolicyAdoptionResult:
    fact_id: UUID
    request_id: UUID
    organization_id: UUID
    controller_principal_id: UUID
    platform_approver_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    authority_revision_before: int
    authority_revision_after: int
    added_capabilities: tuple[str, ...]
    request_revision: int


class ControllerPolicyAdoptionError(RuntimeError):
    """Base class for explicit legacy controller-policy adoption outcomes."""


class ControllerPolicyAdoptionForbidden(ControllerPolicyAdoptionError):
    pass


class ControllerPolicyAdoptionNotFound(ControllerPolicyAdoptionError):
    pass


class ControllerPolicyAdoptionConflict(ControllerPolicyAdoptionError):
    pass


class ControllerPolicyAdoptionInvalid(ControllerPolicyAdoptionError):
    pass


class ControllerPolicyAdoptionCommands(Protocol):
    async def request_adoption(
        self, actor: ActorContext, command: RequestControllerPolicyAdoption
    ) -> ControllerPolicyAdoptionRequestResult: ...

    async def withdraw_adoption(
        self, actor: ActorContext, command: WithdrawControllerPolicyAdoption
    ) -> tuple[int, str]: ...

    async def apply_adoption(
        self, actor: PlatformActorContext, command: ApplyControllerPolicyAdoption
    ) -> ControllerPolicyAdoptionResult: ...

    async def get_adoption(
        self, actor: ActorContext, request_id: UUID
    ) -> ControllerPolicyAdoptionDetail: ...

    async def get_review(
        self, actor: PlatformActorContext, request_id: UUID
    ) -> ControllerPolicyAdoptionReview: ...


class ControllerPolicyAdoptionReader(Protocol):
    async def list_adoptions(
        self, actor: PlatformActorContext, query: ListControllerPolicyAdoptions
    ) -> tuple[ControllerPolicyAdoptionSummary, ...]: ...
