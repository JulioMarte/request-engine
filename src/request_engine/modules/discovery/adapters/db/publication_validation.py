from datetime import UTC, datetime

from request_engine.modules.discovery.application.commands.publication import (
    PublishDiscoverySupplyCommand,
)


def validated_publication_intent(
    command: PublishDiscoverySupplyCommand,
) -> tuple[datetime, datetime | None, str, bool]:
    start = command.effective_start
    end = command.effective_end
    if start.utcoffset() is None or (end is not None and end.utcoffset() is None):
        raise ValueError("discovery publication dates must be timezone-aware")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC) if end is not None else None
    if end is not None and end <= start:
        raise ValueError("effective_end must be after effective_start")
    visibility = command.provider_visibility.strip().lower()
    if visibility not in {"hidden", "public"}:
        raise ValueError("provider_visibility must be hidden or public")
    if visibility == "public" and command.resource_id is None:
        raise ValueError("public provider visibility requires resource_id")
    return start, end, visibility, command.effective_start_is_resolved_now
