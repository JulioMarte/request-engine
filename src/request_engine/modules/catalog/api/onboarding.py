from request_engine.modules.catalog.adapters.db.onboarding_reader import (
    PostgresCatalogOnboardingReader,
)
from request_engine.modules.catalog.contracts.onboarding import CatalogOnboardingReadinessReader
from request_engine.platform.db.session import SessionFactory


def build_onboarding_catalog_reader(
    session_factory: SessionFactory,
) -> CatalogOnboardingReadinessReader:
    return PostgresCatalogOnboardingReader(session_factory)
