import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def fingerprint(capability: str, values: dict[str, object]) -> str:
    canonical = json.dumps(
        {"capability": capability, **values},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def acquire(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    idempotency_key: str,
    command_fingerprint: str,
) -> tuple[UUID, dict[str, object] | None]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT idempotency_id, result_data, replay
                      FROM request_cmd.acquire_idempotency(
                        :organization_id, :principal_id, :capability,
                        :idempotency_key, :fingerprint
                      )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "capability": capability,
                    "idempotency_key": idempotency_key,
                    "fingerprint": command_fingerprint,
                },
            )
        )
        .mappings()
        .one()
    )
    record_id = cast(UUID, row["idempotency_id"])
    if cast(bool, row["replay"]):
        return record_id, cast(dict[str, object], row["result_data"])
    return record_id, None


async def complete(
    session: AsyncSession,
    idempotency_id: UUID,
    result: dict[str, object],
) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT request_cmd.complete_idempotency(
                    :idempotency_id, CAST(:result AS jsonb)
                )
                """
            ),
            {
                "idempotency_id": idempotency_id,
                "result": json.dumps(result, separators=(",", ":")),
            },
        )
    ).one()
    if row[0] is not True:
        raise RuntimeError(f"idempotency record {idempotency_id} could not be completed")
