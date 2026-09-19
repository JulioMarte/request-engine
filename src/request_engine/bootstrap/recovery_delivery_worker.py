from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.secrets.delivery_worker import (
    PostgresRecoveryDeliveryLeaseStore,
    RecoveryDeliveryLease,
    RecoveryDeliveryProcessor,
)
from request_engine.platform.worker.runtime import FencedWorkerRuntime, WorkerRuntimeConfig


def build_recovery_delivery_worker(
    worker_session_factory: SessionFactory,
    delivery: RecoverySecretDelivery,
    *,
    config: WorkerRuntimeConfig | None = None,
) -> FencedWorkerRuntime[RecoveryDeliveryLease]:
    """Compose the technical delivery stream under the worker credential."""

    store = PostgresRecoveryDeliveryLeaseStore(worker_session_factory)
    return FencedWorkerRuntime(
        store,
        RecoveryDeliveryProcessor(store, delivery),
        config=config,
    )
