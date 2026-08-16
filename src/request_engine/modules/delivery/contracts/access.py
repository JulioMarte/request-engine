from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast
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


class DeliveryPolicyValidationError(ValueError):
    """The immutable OfferingVersion delivery policy is not canonical."""


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


def parse_delivery_policy(
    raw: object,
    *,
    known_provider_keys: Collection[str] | None = None,
) -> tuple[AccessPolicy, ...]:
    """Parse and validate the canonical immutable Delivery policy.

    PostgreSQL independently enforces all provider-independent structural
    invariants so direct SQL/import paths cannot persist malformed policy.
    Configuration boundaries that know the installed provider registry should
    pass ``known_provider_keys`` to reject unconfigured providers before the
    OfferingVersion is persisted.
    """

    if not isinstance(raw, dict):
        raise DeliveryPolicyValidationError("delivery_policy must be a JSON object")

    access_raw = cast(dict[object, object], raw).get("access", [])
    if not isinstance(access_raw, list):
        raise DeliveryPolicyValidationError("delivery_policy.access must be an array")

    provider_keys = frozenset(known_provider_keys) if known_provider_keys is not None else None
    policies: list[AccessPolicy] = []
    seen_keys: set[str] = set()

    for index, raw_item in enumerate(cast(list[object], access_raw)):
        context = f"delivery_policy.access[{index}]"
        if not isinstance(raw_item, dict):
            raise DeliveryPolicyValidationError(f"{context} must be an object")
        item = cast(dict[object, object], raw_item)

        access_key = _required_policy_string(item, "key", context)
        if access_key in seen_keys:
            raise DeliveryPolicyValidationError(
                f"delivery_policy.access contains duplicate key {access_key!r}"
            )
        seen_keys.add(access_key)

        kind_raw = _required_policy_string(item, "kind", context)
        try:
            kind = AccessKind(kind_raw)
        except ValueError as exc:
            raise DeliveryPolicyValidationError(
                f"{context}.kind has unsupported value {kind_raw!r}"
            ) from exc

        provider_key: str | None = None
        if "provider" in item:
            provider_key = _required_policy_string(item, "provider", context)
            if provider_keys is not None and provider_key not in provider_keys:
                raise DeliveryPolicyValidationError(
                    f"{context}.provider is not configured: {provider_key!r}"
                )

        provisioning_raw = item.get("provisioning", ProvisioningMode.IMMEDIATE.value)
        if not isinstance(provisioning_raw, str):
            raise DeliveryPolicyValidationError(f"{context}.provisioning must be a string")
        try:
            provisioning_mode = ProvisioningMode(provisioning_raw)
        except ValueError as exc:
            raise DeliveryPolicyValidationError(
                f"{context}.provisioning has unsupported value {provisioning_raw!r}"
            ) from exc

        public_data_raw = item.get("public_data", {})
        if not isinstance(public_data_raw, dict):
            raise DeliveryPolicyValidationError(f"{context}.public_data must be an object")
        public_data = dict(cast(dict[str, object], public_data_raw))

        if (
            provisioning_mode is ProvisioningMode.IMMEDIATE
            and provider_key is None
            and not public_data
        ):
            raise DeliveryPolicyValidationError(
                f"{context} immediate static access requires non-empty public_data"
            )

        policies.append(
            AccessPolicy(
                access_key=access_key,
                kind=kind,
                provider_key=provider_key,
                provisioning_mode=provisioning_mode,
                public_data=public_data,
            )
        )

    return tuple(policies)


def _required_policy_string(
    item: dict[object, object],
    field: str,
    context: str,
) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value or value != value.strip():
        raise DeliveryPolicyValidationError(f"{context}.{field} must be a non-empty trimmed string")
    return value


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
    async def provision(self, request: ProvisionAccessRequest) -> ProvisionedAccess:
        """Create or reuse one artifact idempotently by ``materialization_key``."""

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
