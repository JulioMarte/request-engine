from request_engine.modules.delivery.adapters.db.complete_service import complete_service
from request_engine.modules.delivery.adapters.db.end_resource_activity import (
    end_resource_activity,
)
from request_engine.modules.delivery.adapters.db.pause_service import pause_service
from request_engine.modules.delivery.adapters.db.resume_service import resume_service
from request_engine.modules.delivery.adapters.db.start_resource_activity import (
    start_resource_activity,
)
from request_engine.modules.delivery.adapters.db.start_service import start_service
from request_engine.modules.delivery.application.resource_activity_commands import (
    EndResourceActivityCommand,
    StartResourceActivityCommand,
)
from request_engine.modules.delivery.application.service_session_commands import (
    CompleteServiceCommand,
    PauseServiceCommand,
    ResumeServiceCommand,
    StartServiceCommand,
)
from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ServiceSession,
)
from request_engine.platform.db.session import SessionFactory


class PostgresLiveServiceOperations:
    """Small composition adapter for F3 live-service command implementations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def start_service(self, command: StartServiceCommand) -> ServiceSession:
        return await start_service(self._session_factory, command)

    async def pause_service(self, command: PauseServiceCommand) -> ServiceSession:
        return await pause_service(self._session_factory, command)

    async def resume_service(self, command: ResumeServiceCommand) -> ServiceSession:
        return await resume_service(self._session_factory, command)

    async def complete_service(self, command: CompleteServiceCommand) -> ServiceSession:
        return await complete_service(self._session_factory, command)

    async def start_resource_activity(
        self,
        command: StartResourceActivityCommand,
    ) -> ResourceActivity:
        return await start_resource_activity(self._session_factory, command)

    async def end_resource_activity(
        self,
        command: EndResourceActivityCommand,
    ) -> ResourceActivity:
        return await end_resource_activity(self._session_factory, command)
