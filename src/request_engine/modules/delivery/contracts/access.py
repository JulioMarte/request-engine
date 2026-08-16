from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class AccessKind(StrEnum):
    VIDEO_LINK = "video_link"
    PHONE = "phone"
    PHYSICAL_LOCATION = "physical_location"
    INSTRUCTIONS = "instructions"
    EXTERNAL_SESSION = "external_session"


class AccessStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    REVOKED = "revoked"


class ProvisioningMode(StrEnum):
    IMMEDIATE = "immediate"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class DeliveryWorkClaim:
    organization_id: UUID
    message_id: UUID
    claim_token: UUID


@dataclass(frozen=True, slots=True)
class ReservationAccessSource:
    organization_id: UUID
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    access_key: str
    kind: AccessKind
    provider_key: str | None
    provisioning_mode: ProvisioningMode
    public_data: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReservationAccess:
    id: UUID
    organization_id: UUID
    reservation_id: UUID
    reservation_revision: int
    access_key: str
    kind: AccessKind
    provider_key: str | None
    materialization_key: str
    status: AccessStatus
    access_uri: str | None
    external_ref: str | None
    public_data: dict[str, object]
    provisioned_at: datetime | None
    revoked_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProvisionAccessRequest:
    source: ReservationAccessSource
    access_key: str
    kind: AccessKind
    public_data: dict[str, object]
    materialization_key: str


@dataclass(frozen=True, slots=True)
class ProvisionedAccess:
    access_uri: str | None
    external_ref: str | None
    public_data: dict[str, object]


@dataclass(frozen=True, slots=True)
class RevokeAccessRequest:
    organization_id: UUID
    reservation_id: UUID
    reservation_revision: int
    access_key: str
    kind: AccessKind
    materialization_key: str
    access_uri: str | None
    external_ref: str | None
    public_data: dict[str, object]


class DeliveryPolicyReader(Protocol):
    async def get_access_policies(
        self, organization_id: UUID, offering_version_id: UUID
    ) -> tuple[AccessPolicy, ...]: ...


class ReservationAccessRepository(Protocol):
    async def confirmed_source_is_current(
        self,
        source: ReservationAccessSource,
        work_claim: DeliveryWorkClaim,
    ) -> bool: ...

    async def get_by_key(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        reservation_revision: int,
        access_key: str,
    ) -> ReservationAccess | None: ...

    async def ensure_pending(
        self,
        source: ReservationAccessSource,
        policy: AccessPolicy,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess | None: ...

    async def record_materialized(
        self,
        claim: ReservationAccess,
        materialized: ProvisionedAccess,
    ) -> ReservationAccess: ...

    async def publish_ready_if_current(
        self,
        source: ReservationAccessSource,
        claim: ReservationAccess,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess | None: ...

    async def list_unrevoked_for_reservation(
        self, organization_id: UUID, reservation_id: UUID
    ) -> tuple[ReservationAccess, ...]: ...

    async def mark_revoked_if_current(
        self,
        access: ReservationAccess,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess: ...


class ReservationAccessProvider(Protocol):
    async def provision(self, request: ProvisionAccessRequest) -> ProvisionedAccess: ...

    async def lookup(self, *, materialization_key: str) -> ProvisionedAccess | None:
        """Resolve an already-created artifact without creating a new one."""

    async def revoke(self, request: RevokeAccessRequest) -> None:
        """Idempotently revoke the artifact represented by ``materialization_key``."""


class ReservationAccessLifecyclePort(Protocol):
    async def reconcile_reservation_access(
        self,
        source: ReservationAccessSource,
        *,
        work_claim: DeliveryWorkClaim,
    ) -> tuple[ReservationAccess, ...]: ...

    async def revoke_reservation_access(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        *,
        work_claim: DeliveryWorkClaim,
    ) -> tuple[ReservationAccess, ...]: ...
