from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.delegation_commands import (
    PostgresDelegationCommands,
)
from request_engine.modules.tenancy.application.commands.delegation import (
    CreateDelegationCommand,
    RevokeDelegationCommand,
)
from request_engine.modules.tenancy.application.errors import DelegationForbidden
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _human_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"delegation.create", "delegation.revoke"}),
        principal_kind=PrincipalKind.HUMAN,
    )


def _agent_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"delegation.create", "delegation.revoke"}),
        principal_kind=PrincipalKind.AGENT,
    )


def _commands() -> PostgresDelegationCommands:
    return PostgresDelegationCommands(cast(SessionFactory, object()))


def _create_command() -> CreateDelegationCommand:
    return CreateDelegationCommand(
        delegate_principal_id=uuid4(),
        purpose="Cover reception intake for the holiday week",
        allowed_capabilities=("requests.submit",),
        not_before=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        provenance_reference="delegation-create:test",
        idempotency_key="delegation-create-test",
    )


@pytest.mark.asyncio
async def test_delegation_creation_rejects_non_human_actor_before_any_execution() -> None:
    commands = _commands()
    actor = _agent_actor()

    with pytest.raises(DelegationForbidden, match="HUMAN actor"):
        await commands.create_delegation(actor, _create_command())


@pytest.mark.asyncio
async def test_delegation_creation_rejects_non_operational_and_noncanonical_keys() -> None:
    commands = _commands()
    actor = _human_actor()

    for capabilities, match in (
        (("agent.provision",), "not operational"),
        (("organization.provision",), "not operational"),
        (("future.agent.superuser",), "unknown or non-canonical"),
        (("requests.submit", "requests.submit"), "duplicates"),
    ):
        with pytest.raises(ValueError, match=match):
            await commands.create_delegation(
                actor,
                CreateDelegationCommand(
                    delegate_principal_id=uuid4(),
                    purpose="Cover reception intake for the holiday week",
                    allowed_capabilities=capabilities,
                    not_before=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=8),
                    provenance_reference="delegation-create:test",
                    idempotency_key="delegation-create-test",
                ),
            )


@pytest.mark.asyncio
async def test_delegation_creation_rejects_invalid_input_before_db_access() -> None:
    commands = _commands()
    actor = _human_actor()

    for purpose in ("   ", ""):
        with pytest.raises(ValueError, match="purpose is required"):
            await commands.create_delegation(
                actor,
                CreateDelegationCommand(
                    delegate_principal_id=uuid4(),
                    purpose=purpose,
                    allowed_capabilities=("requests.submit",),
                    not_before=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=8),
                    provenance_reference="delegation-create:test",
                    idempotency_key="delegation-create-test",
                ),
            )
    for provenance in ("   ", "x" * 501):
        with pytest.raises(ValueError, match="between 1 and 500"):
            await commands.create_delegation(
                actor,
                CreateDelegationCommand(
                    delegate_principal_id=uuid4(),
                    purpose="Cover reception intake for the holiday week",
                    allowed_capabilities=("requests.submit",),
                    not_before=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=8),
                    provenance_reference=provenance,
                    idempotency_key="delegation-create-test",
                ),
            )
    with pytest.raises(ValueError, match="idempotency_key is required"):
        await commands.create_delegation(
            actor,
            CreateDelegationCommand(
                delegate_principal_id=uuid4(),
                purpose="Cover reception intake for the holiday week",
                allowed_capabilities=("requests.submit",),
                not_before=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=8),
                provenance_reference="delegation-create:test",
                idempotency_key="   ",
            ),
        )


@pytest.mark.asyncio
async def test_delegation_revocation_does_not_require_a_human_actor() -> None:
    commands = _commands()
    actor = _agent_actor()

    with pytest.raises(ValueError, match="expected_revision must be positive"):
        await commands.revoke_delegation(
            actor,
            RevokeDelegationCommand(
                delegation_id=uuid4(),
                expected_revision=0,
                provenance_reference="delegation-revoke:test",
                idempotency_key="delegation-revoke-test",
            ),
        )
