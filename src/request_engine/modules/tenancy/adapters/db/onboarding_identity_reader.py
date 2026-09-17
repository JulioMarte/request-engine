import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.contracts.onboarding_readiness import (
    IdentityReadinessFacts,
    OnboardingIdentityFacts,
    RecoveryReadinessFacts,
    StaffAdministrationReadinessFacts,
    TenantControlReadinessFacts,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_RECOVERY_UNKNOWN = RecoveryReadinessFacts(known=False, ready=None)


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    if isinstance(value, str | bytes | bytearray):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return cast(dict[str, object], decoded)
    raise RuntimeError("onboarding identity facts payload was not a JSON object")


def _bool_field(mapping: dict[str, object], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"onboarding identity facts field {key!r} is not a boolean")
    return value


def _optional_str_field(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"onboarding identity facts field {key!r} is not a string")
    return value


def _optional_int_field(mapping: dict[str, object], key: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"onboarding identity facts field {key!r} is not an integer")
    return value


def _observed_at_field(mapping: dict[str, object], key: str) -> datetime:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"onboarding identity facts field {key!r} is not a timestamp")
    return datetime.fromisoformat(value)


def _materialize(payload: object) -> OnboardingIdentityFacts:
    mapping = _as_mapping(payload)
    identity = _as_mapping(mapping.get("identity"))
    tenant_control = _as_mapping(mapping.get("tenant_control"))
    staff_administration = _as_mapping(mapping.get("staff_administration"))
    return OnboardingIdentityFacts(
        identity=IdentityReadinessFacts(
            active_controller=_bool_field(identity, "active_controller"),
            authenticatable_controller=_bool_field(identity, "authenticatable_controller"),
        ),
        tenant_control=TenantControlReadinessFacts(
            current_policy_ready=_bool_field(tenant_control, "current_policy_ready"),
            recorded_policy_key=_optional_str_field(tenant_control, "recorded_policy_key"),
        ),
        staff_administration=StaffAdministrationReadinessFacts(
            available=_bool_field(staff_administration, "available"),
        ),
        recovery=_RECOVERY_UNKNOWN,
        observed_at=_observed_at_field(mapping, "observed_at"),
        controller_authority_revision=_optional_int_field(mapping, "controller_authority_revision"),
        policy_revision=_optional_int_field(mapping, "policy_revision"),
    )


class PostgresOnboardingIdentityFactsReader:
    """Read-only tenant-scoped identity/control readiness projection."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_identity_facts(
        self,
        *,
        organization_id: UUID,
    ) -> OnboardingIdentityFacts:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = await session.execute(
                text("SELECT request_engine.read_onboarding_identity_facts(:organization_id)"),
                {"organization_id": organization_id},
            )
            payload = row.scalar_one()
        return _materialize(payload)
