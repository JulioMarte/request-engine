from request_engine.modules.communications.adapters.db.recovery_port import PostgresRecoveryCommunicationPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.platform.db.session import SessionFactory


def build_recovery_communication_port(
    session_factory: SessionFactory,
) -> RecoveryCommunicationPort:
    return PostgresRecoveryCommunicationPort(session_factory)
