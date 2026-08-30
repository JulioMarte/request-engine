from dataclasses import dataclass

from request_engine.modules.queue.adapters.db.copilot_reader import PostgresCopilotQueueReader
from request_engine.modules.queue.adapters.db.intake_control import PostgresQueueIntakeControl
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort
from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class CopilotQueueRuntime:
    queues: CopilotQueueReader
    intake: QueueIntakeControlPort


def build_copilot_queue_runtime(session_factory: SessionFactory) -> CopilotQueueRuntime:
    return CopilotQueueRuntime(
        queues=PostgresCopilotQueueReader(session_factory),
        intake=PostgresQueueIntakeControl(session_factory),
    )
