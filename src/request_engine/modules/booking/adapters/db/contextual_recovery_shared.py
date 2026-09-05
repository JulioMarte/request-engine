# pyright: reportPrivateUsage=false

from typing import Any, Protocol
from uuid import UUID

from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    _build_authoritative_profiles,
    _configuration_fingerprint,
    _effective_context_observations,
    _load_resource_availability_revisions,
    _lock_selected_assignments,
    _require_expected_resource_revisions,
    _resolve_selected_assignments,
)
from request_engine.modules.booking.domain.availability import ResourceAvailability


class RequirementLike(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def ordinal(self) -> int: ...

    @property
    def quantity(self) -> int: ...


def build_authoritative_profiles(*args: Any, **kwargs: Any) -> dict[UUID, ResourceAvailability]:
    return _build_authoritative_profiles(*args, **kwargs)


def configuration_fingerprint(*args: Any, **kwargs: Any) -> str:
    return _configuration_fingerprint(*args, **kwargs)


def effective_context_observations(*args: Any, **kwargs: Any) -> Any:
    return _effective_context_observations(*args, **kwargs)


async def load_resource_availability_revisions(*args: Any, **kwargs: Any) -> dict[UUID, int]:
    return await _load_resource_availability_revisions(*args, **kwargs)


async def lock_selected_assignments(*args: Any, **kwargs: Any) -> None:
    await _lock_selected_assignments(*args, **kwargs)


def require_expected_resource_revisions(*args: Any, **kwargs: Any) -> None:
    _require_expected_resource_revisions(*args, **kwargs)


def resolve_selected_assignments(*args: Any, **kwargs: Any) -> Any:
    return _resolve_selected_assignments(*args, **kwargs)
