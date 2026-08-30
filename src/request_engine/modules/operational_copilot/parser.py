import re
from uuid import UUID

from request_engine.modules.operational_copilot.contracts import (
    CopilotIntent,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    UnsupportedCopilotIntent,
)

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_CREATE = re.compile(
    rf"propose recovery for queue (?P<queue>{_UUID})"
    r"(?: over (?P<days>[0-9]+) days)?",
    re.IGNORECASE,
)
_EXECUTE = re.compile(
    rf"execute recovery proposal (?P<proposal>{_UUID}) "
    rf"for reservation (?P<reservation>{_UUID}) "
    r"source (?P<source>\S+) proposal (?P<target>\S+)"
    r"(?P<override> allow subject override)?"
    r"(?P<silent> without notification)?",
    re.IGNORECASE,
)


def parse_copilot_intent(text: str) -> CopilotIntent:
    normalized = " ".join(text.strip().split())
    lowered = normalized.casefold()
    markers = sum(
        marker in lowered
        for marker in ("propose recovery", "execute recovery")
    )
    if markers > 1:
        raise AmbiguousCopilotIntent("multiple supported actions were requested")

    create = _CREATE.fullmatch(normalized)
    if create is not None:
        days = create.group("days")
        return CreateRecoveryProposalIntent(
            service_queue_id=UUID(create.group("queue")),
            search_days=int(days) if days is not None else 7,
        )

    execute = _EXECUTE.fullmatch(normalized)
    if execute is not None:
        return ExecuteRecoveryIntent(
            proposal_id=UUID(execute.group("proposal")),
            reservation_id=UUID(execute.group("reservation")),
            expected_source_fingerprint=execute.group("source"),
            expected_proposal_fingerprint=execute.group("target"),
            allow_subject_override=execute.group("override") is not None,
            notify=execute.group("silent") is None,
        )

    raise UnsupportedCopilotIntent("input is outside the bounded F6 grammar")
