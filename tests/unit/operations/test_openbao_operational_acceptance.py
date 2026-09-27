from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict,
    PlatformSecretMetadata,
    PlatformSecretNotFound,
)

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "openbao_operational_acceptance",
    ROOT / "scripts/operations/openbao_operational_acceptance.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class _CasStore:
    def __init__(self) -> None:
        self.version = 0
        self.value: str | None = None
        self.operation_id: UUID | None = None
        self.revoked = False

    async def write(
        self,
        *,
        secret_id: UUID,
        value: str,
        expected_version: int | None,
        operation_id: UUID | None = None,
    ) -> PlatformSecretMetadata:
        if expected_version is None:
            if self.version != 0:
                raise PlatformSecretConflict()
        elif expected_version != self.version:
            raise PlatformSecretConflict()
        self.version += 1
        self.value = value
        self.operation_id = operation_id
        self.revoked = False
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=self.version,
            created_at=datetime.now(UTC),
            operation_id=operation_id,
        )

    async def resolve(self, *, secret_id: UUID) -> str:
        del secret_id
        if self.revoked or self.value is None:
            raise PlatformSecretNotFound()
        return self.value

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        if self.revoked:
            raise PlatformSecretNotFound()
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=self.version,
            operation_id=self.operation_id,
        )

    async def revoke(self, *, secret_id: UUID) -> None:
        del secret_id
        self.revoked = True


@pytest.mark.asyncio
async def test_openbao_acceptance_requires_one_cas_winner_and_revocation() -> None:
    secret_id = UUID("11111111-1111-1111-1111-111111111111")

    result = await module.run_acceptance(_CasStore(), secret_id=secret_id)

    assert result["outcome"] == "accepted"
    assert result["initial_version"] == 1
    assert result["winning_version"] == 2
    assert result["exactly_one_cas_winner"] is True
    assert result["conflicting_writer_rejected"] is True
    assert result["winner_operation_marker_verified"] is True
    assert result["winner_value_resolution_verified"] is True
    assert result["revocation_verified"] is True
    assert result["secret_value_persisted_in_evidence"] is False
