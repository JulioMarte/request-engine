from request_engine.modules.operational_recovery.adapters.db.recovery_sweep_store import (
    PostgresRecoverySweepStore,
)
from request_engine.modules.operational_recovery.adapters.worker.recovery_sweep import (
    RecoverySweepConfig,
    RecoverySweepRuntime,
)
from request_engine.platform.db.session import SessionFactory


def build_recovery_sweep(
    worker_session_factory: SessionFactory,
    domain_session_factory: SessionFactory,
    *,
    config: RecoverySweepConfig | None = None,
) -> RecoverySweepRuntime:
    """Compose the bounded sweep with separated discovery and repair credentials."""

    if worker_session_factory is domain_session_factory:
        raise ValueError(
            "worker_session_factory and domain_session_factory must be distinct factories"
        )
    return RecoverySweepRuntime(
        PostgresRecoverySweepStore(worker_session_factory, domain_session_factory),
        config,
    )
