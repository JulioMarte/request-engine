from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.security.native_recovery_delivery import (
    NativeRecoveryDeliveryLease,
    NativeRecoveryDeliveryProcessor,
    PostgresNativeRecoveryDeliveryLeaseStore,
)
from request_engine.platform.worker.runtime import FencedWorkerRuntime, WorkerRuntimeConfig


def build_native_recovery_delivery_worker(
    worker_session_factory: SessionFactory,
    delivery: RecoverySecretDelivery,
    *,
    config: WorkerRuntimeConfig | None = None,
) -> FencedWorkerRuntime[NativeRecoveryDeliveryLease]:
    """Compose asynchronous verified-address recovery delivery."""

    store = PostgresNativeRecoveryDeliveryLeaseStore(worker_session_factory)
    return FencedWorkerRuntime(
        store,
        NativeRecoveryDeliveryProcessor(store, delivery),
        config=config,
    )
