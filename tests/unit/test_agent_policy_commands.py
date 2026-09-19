from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.agent_policy_commands import (
    PostgresAgentPolicyCommands,
)
from request_engine.modules.tenancy.application.commands.agent_policy import (
    ReplaceAgentPolicyCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentPolicyForbidden,
    AgentPolicyInputInvalid,
    AgentPolicyNotFound,
)
from request_engine.modules.tenancy.domain.agent_policy import (
    validate_agent_policy_rule_set,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.operation_risk import OperationRiskClass


def _human_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"agent.policy.read", "agent.manage_policy"}),
        principal_kind=PrincipalKind.HUMAN,
    )


def _agent_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"agent.policy.read", "agent.manage_policy"}),
        principal_kind=PrincipalKind.AGENT,
    )


def _replace_command(**overrides: Any) -> ReplaceAgentPolicyCommand:
    values: dict[str, Any] = {
        "agent_principal_id": uuid4(),
        "allowed_capabilities": ("requests.submit",),
        "denied_capabilities": ("queue.join",),
        "risk_ceiling": OperationRiskClass.REVERSIBLE_WRITE,
        "max_mutations_per_minute": 30,
        "provenance_reference": "agent-policy:test",
        "idempotency_key": "policy-test",
    }
    values.update(overrides)
    return ReplaceAgentPolicyCommand(**values)


class _FakeResult:
    def __init__(self, *, scalar: Any = None, rows: list[dict[str, Any]] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows if rows is not None else []

    def scalar_one(self) -> Any:
        return self._scalar

    def mappings(self) -> "_FakeResult":
        return self

    def one(self) -> dict[str, Any]:
        assert len(self._rows) == 1
        return self._rows[0]

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeBegin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.executed: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.executed.append((str(statement), params or {}))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def begin(self) -> _FakeBegin:
        return _FakeBegin()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSessionFactory:
    def __init__(self, outcomes: list[Any]) -> None:
        self.session = _FakeSession(outcomes)

    def __call__(self) -> _FakeSession:
        return self.session

    def commands(self) -> PostgresAgentPolicyCommands:
        return PostgresAgentPolicyCommands(self)  # type: ignore[arg-type]


def _dbapi_error(state: str) -> DBAPIError:
    class _Orig(Exception):
        def __init__(self) -> None:
            super().__init__(state)
            self.sqlstate = state

    return DBAPIError("SELECT request_engine.upsert_agent_policy()", {}, _Orig())


def _idempotency_rows(
    replay: bool, result_data: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "idempotency_id": uuid4(),
            "replay": replay,
            "result_data": result_data,
        }
    ]


def _policy_row() -> dict[str, Any]:
    return {
        "allowed_capabilities": ["requests.submit"],
        "denied_capabilities": ["queue.join"],
        "risk_ceiling": "reversible_write",
        "max_mutations_per_minute": 30,
        "policy_revision": 7,
        "provenance_reference": "agent-policy:test",
    }


@pytest.mark.asyncio
async def test_agent_policy_rejects_non_human_actor_before_any_execution() -> None:
    factory = _FakeSessionFactory([])
    commands = factory.commands()
    actor = _agent_actor()

    with pytest.raises(AgentPolicyForbidden, match="HUMAN actor"):
        await commands.read_policy(actor, uuid4())
    with pytest.raises(AgentPolicyForbidden, match="HUMAN actor"):
        await commands.replace_policy(actor, _replace_command())
    assert factory.session.executed == []


@pytest.mark.asyncio
async def test_agent_policy_rejects_invalid_rule_sets_before_db_access() -> None:
    factory = _FakeSessionFactory([])
    commands = factory.commands()
    actor = _human_actor()

    invalid_cases = [
        _replace_command(allowed_capabilities=("future.agent.superuser",)),
        _replace_command(allowed_capabilities=("requests.submit", "requests.submit")),
        _replace_command(denied_capabilities=("requests.submit",)),
        _replace_command(risk_ceiling=OperationRiskClass.AUTHORITY_CHANGE),
        _replace_command(max_mutations_per_minute=0),
        _replace_command(max_mutations_per_minute=-5),
        _replace_command(provenance_reference="   "),
        _replace_command(idempotency_key="   "),
    ]
    for command in invalid_cases:
        with pytest.raises(ValueError):
            await commands.replace_policy(actor, command)
    assert factory.session.executed == []


def test_agent_policy_risk_ceiling_rejects_authority_change_and_garbage() -> None:
    with pytest.raises(ValueError, match="authority_change"):
        validate_agent_policy_rule_set(
            risk_ceiling=OperationRiskClass.AUTHORITY_CHANGE,
            max_mutations_per_minute=1,
            allowed_capabilities=(),
            denied_capabilities=(),
        )
    with pytest.raises(ValueError):
        OperationRiskClass("garbage")


@pytest.mark.asyncio
async def test_replace_policy_maps_sql_result_to_revision_and_completes_idempotency() -> None:
    factory = _FakeSessionFactory(
        [
            _FakeResult(),
            _FakeResult(rows=_idempotency_rows(replay=False)),
            _FakeResult(scalar=7),
            _FakeResult(scalar=True),
        ]
    )
    commands = factory.commands()
    actor = _human_actor()
    command = _replace_command()

    policy_revision = await commands.replace_policy(actor, command)

    assert policy_revision == 7
    statements = [statement for statement, _ in factory.session.executed]
    assert any("upsert_agent_policy" in statement for statement in statements)
    upsert_params = next(
        params
        for statement, params in factory.session.executed
        if "upsert_agent_policy" in statement
    )
    assert upsert_params["agent_principal_id"] == command.agent_principal_id
    assert upsert_params["allowed_capabilities"] == ["requests.submit"]
    assert upsert_params["denied_capabilities"] == ["queue.join"]
    assert upsert_params["risk_ceiling"] == "reversible_write"
    assert upsert_params["max_mutations_per_minute"] == 30
    assert upsert_params["provenance_reference"] == "agent-policy:test"


@pytest.mark.asyncio
async def test_replace_policy_replays_completed_idempotency_without_db_call() -> None:
    factory = _FakeSessionFactory(
        [
            _FakeResult(),
            _FakeResult(rows=_idempotency_rows(replay=True, result_data={"policy_revision": 7})),
        ]
    )
    commands = factory.commands()

    policy_revision = await commands.replace_policy(_human_actor(), _replace_command())

    assert policy_revision == 7
    statements = [statement for statement, _ in factory.session.executed]
    assert not any("upsert_agent_policy" in statement for statement in statements)


@pytest.mark.asyncio
async def test_replace_policy_maps_sqlstates_to_typed_errors() -> None:
    for sqlstate, expected in (
        ("22023", AgentPolicyInputInvalid),
        ("P0002", AgentPolicyNotFound),
        ("55000", AgentPolicyForbidden),
    ):
        factory = _FakeSessionFactory(
            [
                _FakeResult(),
                _FakeResult(rows=_idempotency_rows(replay=False)),
                _dbapi_error(sqlstate),
            ]
        )
        with pytest.raises(expected):
            await factory.commands().replace_policy(_human_actor(), _replace_command())


@pytest.mark.asyncio
async def test_read_policy_maps_row_to_agent_policy() -> None:
    agent_principal_id = uuid4()
    factory = _FakeSessionFactory(
        [
            _FakeResult(),
            _FakeResult(rows=[_policy_row()]),
        ]
    )
    commands = factory.commands()

    policy = await commands.read_policy(_human_actor(), agent_principal_id)

    assert policy.agent_principal_id == agent_principal_id
    assert policy.allowed_capabilities == ("requests.submit",)
    assert policy.denied_capabilities == ("queue.join",)
    assert policy.risk_ceiling is OperationRiskClass.REVERSIBLE_WRITE
    assert policy.max_mutations_per_minute == 30
    assert policy.policy_revision == 7
    assert policy.provenance_reference == "agent-policy:test"


@pytest.mark.asyncio
async def test_read_policy_raises_not_found_when_row_absent() -> None:
    factory = _FakeSessionFactory([_FakeResult(), _FakeResult(rows=[])])

    with pytest.raises(AgentPolicyNotFound):
        await factory.commands().read_policy(_human_actor(), uuid4())
