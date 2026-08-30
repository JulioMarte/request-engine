import re
from datetime import time

from request_engine.modules.operational_copilot.references import (
    CopilotParsedIntent,
    ExtendNamedResourceTodayIntent,
    PublishNamedResourceDiscoveryIntent,
    ShowCurrentAtRiskReservationsIntent,
    StopWalkInsRestOfDayIntent,
)

_EXTEND = re.compile(
    r"^(?P<resource>.+?) will work until "
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<period>am|pm) today$",
    re.IGNORECASE,
)
_PUBLISH = re.compile(
    r"^publish (?P<resource>.+?) for (?P<offering>.+?) discovery$",
    re.IGNORECASE,
)


def parse_roadmap_intent(text: str) -> CopilotParsedIntent | None:
    lowered = text.casefold()
    if lowered == "stop accepting walk-ins for the rest of the day":
        return StopWalkInsRestOfDayIntent()
    if lowered == "show me which reservations are at risk":
        return ShowCurrentAtRiskReservationsIntent()
    if match := _EXTEND.fullmatch(text):
        return ExtendNamedResourceTodayIntent(
            resource_reference=match.group("resource").strip(),
            target_local_time=_clock_time(match),
        )
    if match := _PUBLISH.fullmatch(text):
        return PublishNamedResourceDiscoveryIntent(
            resource_reference=match.group("resource").strip(),
            offering_reference=match.group("offering").strip(),
        )
    return None


def _clock_time(match: re.Match[str]) -> time:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")
    if hour < 1 or hour > 12 or minute > 59:
        raise ValueError("invalid roadmap clock time")
    if hour == 12:
        hour = 0
    if match.group("period").casefold() == "pm":
        hour += 12
    return time(hour, minute)
