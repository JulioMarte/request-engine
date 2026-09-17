from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext


class ResourceAuthorityOperation(StrEnum):
    """Business operations whose effective resource authority may be inspected."""

    APPOINTMENTS_BOOK = "appointments.book"
    BOOKING_MANAGE_SUPPLY = "booking.manage_supply"


class ResourceAuthorityDecisionKind(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class ResourceAuthorityQuery:
    """One typed self-inspection request over an explicit supported operation."""

    operation: ResourceAuthorityOperation
    subject_party_id: UUID | None = None
    authority_party_id: UUID | None = None

    def __post_init__(self) -> None:
        try:
            operation = ResourceAuthorityOperation(self.operation)
        except ValueError:
            raise ValueError(
                f"unsupported resource authority operation {self.operation!r}"
            ) from None
        object.__setattr__(self, "operation", operation)
        if operation is ResourceAuthorityOperation.APPOINTMENTS_BOOK:
            if self.subject_party_id is None:
                raise ValueError("appointments.book requires subject_party_id")
            if self.authority_party_id is not None:
                raise ValueError("appointments.book does not accept authority_party_id")
            return
        if self.authority_party_id is None:
            raise ValueError("booking.manage_supply requires authority_party_id")
        if self.subject_party_id is not None:
            raise ValueError("booking.manage_supply does not accept subject_party_id")


@dataclass(frozen=True, slots=True)
class ResourceAuthorityDecision:
    """Advisory owner-computed decision; never a guarantee of a future command."""

    decision: ResourceAuthorityDecisionKind
    reason_codes: tuple[str, ...]
    authority_revision: int
    representation_revision: int | None = None


class ResourceAuthorityTargetNotFound(LookupError):
    """The queried target Party is absent or not visible in the current tenant."""


class ResourceAuthorityInspector(Protocol):
    """Owner-backed read-only resolution of effective resource authority."""

    supported_operations: frozenset[str]

    async def inspect(
        self, actor: ActorContext, query: ResourceAuthorityQuery
    ) -> ResourceAuthorityDecision: ...
