"""Connection refusal fails closed before the provider receives any candidate."""

import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.secrets.delivery import RecoveryDeliveryRetryable, StagedRecoverySecret
from request_engine.platform.secrets.durable_proof_inventory import DurableProofInventoryStore

pytestmark = [pytest.mark.unit, pytest.mark.security]


class NoProviderCalls:
    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        pytest.fail("database admission failed; provider must not receive a secret")

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        pytest.fail("outage cannot destroy a possible winner")

    async def read(self, *, reference: str) -> str:
        pytest.fail("recorder does not resolve plaintext")


@pytest.mark.asyncio
async def test_database_admission_outage_is_sanitized_retryable_without_staging() -> None:
    # An exclusively bound, non-listening local socket deterministically refuses
    # the connection. No PostgreSQL state, installation credentials or mock DB.
    with socket.socket() as refusal:
        refusal.bind(("127.0.0.1", 0))
        port = refusal.getsockname()[1]
        engine = create_postgres_engine(
            f"postgresql+asyncpg://recorder:private-sentinel@127.0.0.1:{port}/receipts"
        )
        store = DurableProofInventoryStore(
            NoProviderCalls(),
            create_session_factory(engine),
            backend_id=uuid4(),
            mount="secret",
        )
        try:
            with pytest.raises(RecoveryDeliveryRetryable) as error:
                await store.stage(
                    case_id=uuid4(),
                    generation=1,
                    secret="proof-private-sentinel",
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            assert str(error.value) == "retained proof recorder unavailable"
            assert error.value.__suppress_context__
        finally:
            await engine.dispose()
