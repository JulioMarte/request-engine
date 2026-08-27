from request_engine.modules.operational_recovery.adapters.db.execution_repository import (
    ExecutionRepositoryMixin,
)
from request_engine.modules.operational_recovery.adapters.db.proposal_repository import (
    ProposalRepositoryMixin,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryRepository(
    ProposalRepositoryMixin,
    ExecutionRepositoryMixin,
    RecoveryRepository,
):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
