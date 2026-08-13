class IdempotencyConflict(Exception):
    """Raised when one idempotency identity is reused for a different command fingerprint."""

    def __init__(self, capability: str, idempotency_key: str) -> None:
        super().__init__(
            f"idempotency key {idempotency_key!r} was already used for a different {capability!r} command"
        )
        self.capability = capability
        self.idempotency_key = idempotency_key
