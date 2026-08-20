from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from request_engine.modules.tenancy.adapters.db.operational_authority import (
    require_operational_authority,
)
from request_engine.modules.tenancy.application.commands.update_organization_operational_profile import (
    OrganizationOperationalProfile,
    UpdateOrganizationOperationalProfileCommand,
)
from request_engine.modules.tenancy.contracts.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


class PostgresOperationalProfileCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def update_organization_operational_profile(
        self,
        command: UpdateOrganizationOperationalProfileCommand,
    ) -> OrganizationOperationalProfile:
        _validate_profile(command)
        fingerprint = command_fingerprint(
            "tenancy.update_organization_operational_profile",
            {
                "authority_party_id": command.authority_party_id,
                "legal_name": command.legal_name,
                "default_timezone": command.default_timezone,
                "default_locale": command.default_locale,
                "default_currency": command.default_currency,
                "operational_status": command.operational_status,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="tenancy.update_organization_operational_profile",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _profile_from_json(cast(dict[str, object], replay["profile"]))

            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.organizations
                               SET legal_name = :legal_name,
                                   default_timezone = :default_timezone,
                                   default_locale = :default_locale,
                                   default_currency = :default_currency,
                                   operational_status = :operational_status,
                                   updated_at = clock_timestamp()
                             WHERE id = :organization_id
                            RETURNING id, legal_name, default_timezone,
                                      default_locale, default_currency, operational_status
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "legal_name": command.legal_name,
                            "default_timezone": command.default_timezone,
                            "default_locale": command.default_locale,
                            "default_currency": command.default_currency,
                            "operational_status": command.operational_status,
                        },
                    )
                )
                .mappings()
                .one()
            )
            profile = OrganizationOperationalProfile(
                organization_id=cast(UUID, row["id"]),
                legal_name=cast(str | None, row["legal_name"]),
                default_timezone=cast(str | None, row["default_timezone"]),
                default_locale=cast(str | None, row["default_locale"]),
                default_currency=cast(str | None, row["default_currency"]),
                operational_status=cast(str, row["operational_status"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="tenancy.update_organization_operational_profile",
                aggregate_kind="Organization",
                aggregate_id=command.organization_id,
                idempotency_id=idempotency_id,
                details={"authority": authority.audit_details()},
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"profile": _profile_to_json(profile)},
            )
            return profile


def _validate_profile(command: UpdateOrganizationOperationalProfileCommand) -> None:
    if command.legal_name is not None and not command.legal_name.strip():
        raise ValueError("legal_name cannot be blank")
    if command.default_timezone is not None:
        if not command.default_timezone.strip():
            raise ValueError("default_timezone cannot be blank")
        try:
            ZoneInfo(command.default_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("default_timezone must be a valid IANA timezone") from exc
    if command.default_locale is not None and not command.default_locale.strip():
        raise ValueError("default_locale cannot be blank")
    if command.default_currency is not None:
        currency = command.default_currency
        if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
            raise ValueError("default_currency must be an uppercase three-letter code")
    if command.operational_status not in {"active", "inactive"}:
        raise ValueError("operational_status must be active or inactive")


def _profile_to_json(profile: OrganizationOperationalProfile) -> dict[str, object]:
    return {
        "organization_id": str(profile.organization_id),
        "legal_name": profile.legal_name,
        "default_timezone": profile.default_timezone,
        "default_locale": profile.default_locale,
        "default_currency": profile.default_currency,
        "operational_status": profile.operational_status,
    }


def _profile_from_json(value: dict[str, object]) -> OrganizationOperationalProfile:
    return OrganizationOperationalProfile(
        organization_id=UUID(cast(str, value["organization_id"])),
        legal_name=cast(str | None, value.get("legal_name")),
        default_timezone=cast(str | None, value.get("default_timezone")),
        default_locale=cast(str | None, value.get("default_locale")),
        default_currency=cast(str | None, value.get("default_currency")),
        operational_status=cast(str, value["operational_status"]),
    )
