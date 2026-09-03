from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.commands.bootstrap_operational_authority import (
    BootstrapOperationalAuthorityCommand,
    BootstrapOperationalAuthorityState,
)
from request_engine.modules.tenancy.contracts.authority import AuthorityKind
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    MANAGE_DISCOVERY_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
)

_CAPABILITY = "organization.bootstrap"
_SCOPE_KEYS = tuple(
    sorted(
        {
            MANAGE_OPERATIONAL_PROFILE_SCOPE,
            MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            MANAGE_COMMERCIAL_TERMS_SCOPE,
            MANAGE_DISCOVERY_SCOPE,
        }
    )
)


class PostgresBootstrapOperationalAuthorityCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def bootstrap_operational_authority(
        self,
        command: BootstrapOperationalAuthorityCommand,
    ) -> BootstrapOperationalAuthorityState:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {"authority_party_id": command.authority_party_id},
        )
        async with tenant_transaction(
            self._session_factory, command.organization_id
        ) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["authority"]))

            principal = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, principal_kind, active
                            FROM request_engine.principals
                            WHERE organization_id = :organization_id
                              AND id = :principal_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "principal_id": command.principal_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if principal is None or principal["active"] is not True:
                raise PermissionError("bootstrap principal is missing or inactive")

            party = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, party_kind, active
                            FROM request_engine.parties
                            WHERE organization_id = :organization_id
                              AND id = :party_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "party_id": command.authority_party_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            invalid_party = (
                party is None
                or party["active"] is not True
                or party["party_kind"] != "organization"
            )
            if invalid_party:
                raise ValueError(
                    "authority_party_id must be an active organization Party"
                )

            existing_rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT scope_key, authority_kind
                            FROM request_engine.representations
                            WHERE organization_id = :organization_id
                              AND principal_id = :principal_id
                              AND represented_party_id = :party_id
                              AND status = 'active'
                              AND valid_from <= clock_timestamp()
                              AND (valid_until IS NULL OR valid_until > clock_timestamp())
                              AND scope_key = ANY(CAST(:scope_keys AS text[]))
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "principal_id": command.principal_id,
                            "party_id": command.authority_party_id,
                            "scope_keys": list(_SCOPE_KEYS),
                        },
                    )
                )
                .mappings()
                .all()
            )
            existing = {
                cast(str, row["scope_key"]): cast(str, row["authority_kind"])
                for row in existing_rows
            }
            incompatible = [
                scope
                for scope, kind in existing.items()
                if kind != AuthorityKind.DELEGATED.value
            ]
            if incompatible:
                raise PermissionError(
                    "incompatible active operational authority already exists"
                )

            for scope_key in _SCOPE_KEYS:
                if scope_key in existing:
                    continue
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.representations (
                            organization_id,
                            principal_id,
                            represented_party_id,
                            authority_kind,
                            scope_key,
                            valid_until
                        ) VALUES (
                            :organization_id,
                            :principal_id,
                            :party_id,
                            'delegated',
                            :scope_key,
                            NULL
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "principal_id": command.principal_id,
                        "party_id": command.authority_party_id,
                        "scope_key": scope_key,
                    },
                )

            state = BootstrapOperationalAuthorityState(
                authority_party_id=command.authority_party_id,
                principal_id=command.principal_id,
                authority_kind=AuthorityKind.DELEGATED,
                scope_keys=_SCOPE_KEYS,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="Party",
                aggregate_id=command.authority_party_id,
                idempotency_id=idempotency_id,
                details={
                    "authority_kind": state.authority_kind.value,
                    "scope_keys": list(state.scope_keys),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority": _state_to_json(state)},
            )
            return state


def _state_to_json(state: BootstrapOperationalAuthorityState) -> dict[str, object]:
    return {
        "authority_party_id": str(state.authority_party_id),
        "principal_id": str(state.principal_id),
        "authority_kind": state.authority_kind.value,
        "scope_keys": list(state.scope_keys),
    }


def _state_from_json(value: dict[str, object]) -> BootstrapOperationalAuthorityState:
    return BootstrapOperationalAuthorityState(
        authority_party_id=UUID(cast(str, value["authority_party_id"])),
        principal_id=UUID(cast(str, value["principal_id"])),
        authority_kind=AuthorityKind(cast(str, value["authority_kind"])),
        scope_keys=tuple(cast(list[str], value["scope_keys"])),
    )
