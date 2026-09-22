from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlatformReadiness:
    managed_smtp_source: str
    smtp_active_revision: int | None
    smtp_last_validated_at: datetime | None
    smtp_last_provider_test_outcome: str | None
    smtp_last_provider_test_at: datetime | None
    smtp_secret_configured: bool
    backup_evidence: str = "unknown"
    restore_drill: str = "unknown"
    clone_fence: str = "unknown"
