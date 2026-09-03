from request_engine.modules.queue.adapters.db.onboarding_reader import (
    PostgresQueueOnboardingReader,
)
from request_engine.modules.queue.contracts.onboarding import QueueOnboardingReadinessReader
from request_engine.platform.db.session import SessionFactory


def build_onboarding_queue_reader(
    session_factory: SessionFactory,
) -> QueueOnboardingReadinessReader:
    return PostgresQueueOnboardingReader(session_factory)
