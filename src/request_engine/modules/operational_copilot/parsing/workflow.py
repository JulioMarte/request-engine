from request_engine.modules.operational_copilot.contracts import (
    CopilotIntent,
    ExtendRecoveryDayIntent,
    SetRecoveryIntakeIntent,
)
from request_engine.modules.operational_copilot.parsing.patterns import (
    DATETIME_PATTERN,
    UINT_PATTERN,
    UUID_PATTERN,
    compile_pattern,
    parse_datetime,
    parse_uint,
    parse_uuid,
)

_INTAKE = compile_pattern(
    rf"(?P<mode>stop|reopen) walk-ins for incident (?P<incident>{UUID_PATTERN}) "
    rf"source revision (?P<source>{UINT_PATTERN}) intake revision (?P<intake>{UINT_PATTERN})"
)
_EXTEND = compile_pattern(
    rf"extend day for incident (?P<incident>{UUID_PATTERN}) "
    rf"assignment (?P<assignment>{UUID_PATTERN}) "
    rf"from (?P<start>{DATETIME_PATTERN}) to (?P<end>{DATETIME_PATTERN}) "
    rf"source revision (?P<source>{UINT_PATTERN}) "
    rf"location revision (?P<location>{UINT_PATTERN}) "
    rf"availability revision (?P<availability>{UINT_PATTERN}) reason (?P<reason>.+)"
)


def parse_workflow_intent(text: str) -> CopilotIntent | None:
    intake = _INTAKE.fullmatch(text)
    if intake is not None:
        return SetRecoveryIntakeIntent(
            incident_id=parse_uuid(intake.group("incident")),
            accepting=intake.group("mode").casefold() == "reopen",
            expected_source_revision=parse_uint(intake.group("source")),
            expected_intake_revision=parse_uint(intake.group("intake")),
        )

    extend = _EXTEND.fullmatch(text)
    if extend is not None:
        return ExtendRecoveryDayIntent(
            incident_id=parse_uuid(extend.group("incident")),
            assignment_id=parse_uuid(extend.group("assignment")),
            start_at=parse_datetime(extend.group("start")),
            end_at=parse_datetime(extend.group("end")),
            expected_source_revision=parse_uint(extend.group("source")),
            expected_location_operational_revision=parse_uint(extend.group("location")),
            expected_resource_availability_revision=parse_uint(extend.group("availability")),
            reason=extend.group("reason").strip(),
        )

    return None
