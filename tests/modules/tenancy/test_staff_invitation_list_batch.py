"""Count executed statements independently of result projection helpers."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.staff_invitation_delivery import (
    PostgresStaffInvitationDeliveryRecorder,
)
from request_engine.modules.tenancy.adapters.db import staff_invitation_commands as owner
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_hundred_invitation_list_uses_constant_statement_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = uuid4()
    actor = ActorContext(
        organization_id=organization,
        principal_id=uuid4(),
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset({"staff.read"}),
    )
    now = datetime.now(UTC)
    rows = [
        dict(
            invitation_id=uuid4(),
            organization_id=organization,
            email=f"u{i}@example.test",
            status="pending",
            generation=i % 3 + 1,
            revision=1,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            membership_id=None,
            principal_id=None,
            binding_id=None,
        )
        for i in range(100)
    ]
    expected = {
        (row["invitation_id"], row["generation"]): "unknown" if i % 2 else "pending"
        for i, row in enumerate(rows)
    }
    session = AsyncSession()
    executed: list[str] = []

    async def execute(statement: object, parameters: dict[str, object]) -> MagicMock:
        sql = str(statement)
        executed.append(sql)
        result = MagicMock()
        if "SELECT EXISTS" in sql:
            result.scalar_one.return_value = True
        elif "FROM request_engine.staff_invitations i" in sql:
            result.mappings.return_value.all.return_value = rows
        elif "unnest" in sql:
            assert parameters == {
                "organization_id": organization,
                "invitation_ids": [row["invitation_id"] for row in rows],
                "generations": [row["generation"] for row in rows],
            }
            result.mappings.return_value.all.return_value = [
                {
                    "invitation_id": row["invitation_id"],
                    "generation": row["generation"],
                    "status": expected[(row["invitation_id"], row["generation"])],
                }
                for row in rows
            ]
        else:
            pytest.fail("unexpected per-invitation delivery query")
        return result

    monkeypatch.setattr(session, "execute", AsyncMock(side_effect=execute))

    @asynccontextmanager
    async def transaction(*args: object):
        async with session.begin():
            yield session

    monkeypatch.setattr(owner, "actor_transaction", transaction)
    commands = owner.PostgresStaffInvitationCommands(
        MagicMock(),
        secret_delivery=None,
        delivery_recorder=PostgresStaffInvitationDeliveryRecorder(),
    )
    result = await commands.list(actor, limit=100)
    assert len(result) == 100
    assert {
        (item.invitation_id, item.generation): item.delivery_status for item in result
    } == expected
    assert len(executed) == 3
    await session.close()


@pytest.mark.asyncio
async def test_batch_is_bounded_deduplicated_and_empty_is_no_io() -> None:
    recorder = PostgresStaffInvitationDeliveryRecorder()
    session = AsyncSession()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    execute = AsyncMock(return_value=result)
    organization, invitation = uuid4(), uuid4()
    async with session.begin():
        session.execute = execute
        assert await recorder.statuses(session, organization_id=organization, generations=()) == {}
        execute.assert_not_awaited()
        with pytest.raises(ValueError):
            await recorder.statuses(
                session, organization_id=organization, generations=((invitation, 1),) * 102
            )
        with pytest.raises(ValueError):
            await recorder.statuses(
                session, organization_id=organization, generations=((invitation, 0),)
            )
        execute.assert_not_awaited()
        assert (
            await recorder.statuses(
                session,
                organization_id=organization,
                generations=((invitation, 2), (invitation, 2)),
            )
            == {}
        )
        assert execute.await_count == 1
        assert execute.await_args is not None
        assert execute.await_args.args[1] == {
            "organization_id": organization,
            "invitation_ids": [invitation],
            "generations": [2],
        }
    await session.close()
