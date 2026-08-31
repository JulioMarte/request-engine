from __future__ import annotations

from typing import Any, cast

from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    SetRecoveryIntakeCommand,
)
from request_engine.platform.security.context import ActorContext

from .f5_recovery_support import f5_actor
from .tenant_sandbox import TenantSandbox, auth

_COPILOT_CAPABILITIES = frozenset(
    {
        "operational_copilot.read",
        "operational_copilot.interpret",
        "operational_copilot.execute",
    }
)


def copilot_actor(sandbox: TenantSandbox) -> ActorContext:
    base = f5_actor(sandbox)
    return ActorContext(
        base.organization_id,
        base.principal_id,
        base.capabilities | _COPILOT_CAPABILITIES,
    )


async def interpret(
    client: Any,
    sandbox: TenantSandbox,
    text: str,
    key: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/operational-copilot/interpret",
        json={"text": text},
        headers=auth(sandbox, idempotency_key=key),
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def execute(
    client: Any,
    sandbox: TenantSandbox,
    text: str,
    key: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/operational-copilot/execute",
        json={"text": text},
        headers=auth(sandbox, idempotency_key=key),
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def execute_tool(
    client: Any,
    sandbox: TenantSandbox,
    path: str,
    body: dict[str, object],
    key: str,
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/operational-copilot/tools{path}",
        json=body,
        headers=auth(sandbox, idempotency_key=key),
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


async def read_tool(client: Any, sandbox: TenantSandbox, path: str) -> Any:
    response = await client.get(
        f"/v1/operational-copilot/tools{path}",
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    return response.json()


def intake_body(command: SetRecoveryIntakeCommand) -> dict[str, object]:
    return {
        "expected_source_revision": command.expected_source_revision,
        "expected_intake_revision": command.expected_intake_revision,
        "accepting": command.accepting,
        "reason": command.reason,
    }
