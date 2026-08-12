class ScheduledActionError(Exception):
    """Base class for durable scheduler failures."""


class ScheduledActionDedupeConflict(ScheduledActionError):
    def __init__(self, dedupe_key: str) -> None:
        super().__init__(f"scheduled action dedupe key {dedupe_key!r} identifies different work")
        self.dedupe_key = dedupe_key
