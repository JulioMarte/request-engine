from request_engine.modules.queue.adapters.db.intake_control import PostgresQueueIntakeControl
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort
from request_engine.platform.db.session import SessionFactory


def build_recovery_intake_control_port(
    session_factory: SessionFactory,
) -> QueueIntakeControlPort:
    return PostgresQueueIntakeControl(session_factory)
