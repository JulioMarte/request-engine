import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def command_fingerprint(capability: str, values: dict[str, object]) -> str:
    """Hash a canonical command payload for idempotency-key reuse protection."""

    canonical = json.dumps(
        {"capability": capability, **values},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def acquire_idempotency(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    idempotency_key: str,
    fingerprint: str,
) -> tuple[UUID, dict[str, object] | None]:
    """Acquire/serialize one idempotency identity and return replay data when completed."""

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT idempotency_id, result_data, replay
                    FROM request_cmd.acquire_idempotency(
                        :organization_id,
                        :principal_id,
                        :capability,
                        :idempotency_key,
                        :fingerprint
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "capability": capability,
                    "idempotency_key": idempotency_key,
                    "fingerprint": fingerprint,
                },
            )
        )
        .mappings()
        .one()
    )

    idempotency_id = cast(UUID, row["idempotency_id"])
    if not cast(bool, row["replay"]):
        return idempotency_id, None

    result_data = row["result_data"]
    if not isinstance(result_data, dict):
        raise RuntimeError(f"completed idempotency record {idempotency_id} has no object result")
    return idempotency_id, cast(dict[str, object], result_data)


async def complete_idempotency(
    session: AsyncSession,
    idempotency_id: UUID,
    result: dict[str, object],
) -> None:
    """Persist the replayable deterministic result for an acquired idempotency identity."""

    completed = (
        await session.execute(
            text(
                """
                SELECT request_cmd.complete_idempotency(
                    :idempotency_id,
                    CAST(:result AS jsonb)
                )
                """
            ),
            {
                "idempotency_id": idempotency_id,
                "result": json.dumps(result, separators=(",", ":")),
            },
        )
    ).scalar_one()
    if completed is not True:
        raise RuntimeError(f"idempotency record {idempotency_id} could not be completed")
