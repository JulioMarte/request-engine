from request_engine.modules.operational_copilot.contracts import (
    CopilotIntent,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.parsing.patterns import (
    UUID_PATTERN,
    compile_pattern,
    parse_uint,
    parse_uuid,
)

_CREATE = compile_pattern(
    rf"propose recovery for queue (?P<queue>{UUID_PATTERN})"
    r"(?: over (?P<days>[0-9]+) days)?"
)
_EXECUTE = compile_pattern(
    rf"execute recovery proposal (?P<proposal>{UUID_PATTERN}) "
    rf"for reservation (?P<reservation>{UUID_PATTERN})"
    r"(?: source (?P<source>\S+) proposal (?P<target>\S+))?"
    r"(?P<override> allow subject override)?"
    r"(?P<silent> without notification)?"
)


def parse_recovery_intent(text: str) -> CopilotIntent | None:
    create = _CREATE.fullmatch(text)
    if create is not None:
        days = create.group("days")
        return CreateRecoveryProposalIntent(
            service_queue_id=parse_uuid(create.group("queue")),
            search_days=parse_uint(days) if days is not None else 7,
        )

    execute = _EXECUTE.fullmatch(text)
    if execute is not None:
        source = execute.group("source")
        target = execute.group("target")
        if (source is None) != (target is None):
            return None
        return ExecuteRecoveryIntent(
            proposal_id=parse_uuid(execute.group("proposal")),
            reservation_id=parse_uuid(execute.group("reservation")),
            expected_source_fingerprint=source,
            expected_proposal_fingerprint=target,
            allow_subject_override=execute.group("override") is not None,
            notify=execute.group("silent") is None,
        )

    return None
