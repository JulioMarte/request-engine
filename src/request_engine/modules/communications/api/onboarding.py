from request_engine.modules.communications.adapters.db.onboarding_reader import (
    PostgresCommunicationsOnboardingReader,
)
from request_engine.modules.communications.contracts.onboarding import (
    CommunicationsOnboardingReadinessReader,
)
from request_engine.platform.db.session import SessionFactory


def build_onboarding_communications_reader(
    session_factory: SessionFactory,
) -> CommunicationsOnboardingReadinessReader:
    return PostgresCommunicationsOnboardingReader(session_factory)
