from dataclasses import dataclass
from datetime import time

from request_engine.modules.operational_copilot.contracts import CopilotIntent


@dataclass(frozen=True, slots=True)
class ExtendNamedResourceTodayIntent:
    resource_reference: str
    target_local_time: time


@dataclass(frozen=True, slots=True)
class StopWalkInsRestOfDayIntent:
    pass


@dataclass(frozen=True, slots=True)
class PublishNamedResourceDiscoveryIntent:
    resource_reference: str
    offering_reference: str


@dataclass(frozen=True, slots=True)
class ShowCurrentAtRiskReservationsIntent:
    pass


CopilotParsedIntent = (
    CopilotIntent
    | ExtendNamedResourceTodayIntent
    | StopWalkInsRestOfDayIntent
    | PublishNamedResourceDiscoveryIntent
    | ShowCurrentAtRiskReservationsIntent
)
