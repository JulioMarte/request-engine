from request_engine.modules.queue.adapters.db.copilot_reader import PostgresCopilotQueueReader
from request_engine.modules.queue.contracts.copilot import CopilotQueueReader
from request_engine.platform.db.session import SessionFactory


def build_copilot_queue_reader(session_factory: SessionFactory) -> CopilotQueueReader:
    return PostgresCopilotQueueReader(session_factory)
