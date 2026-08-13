class IdempotencyConflict(Exception):
    """Raised when one idempotency identity is reused for a different command fingerprint."""

    def __init__(self, capability: str, idempotency_key: str) -> None:
        message = (
            f"idempotency key {idempotency_key!r} was already used for "
            f"a different {capability!r} command"
        )
        super().__init__(message)
        self.capability = capability
        self.idempotency_key = idempotency_key
