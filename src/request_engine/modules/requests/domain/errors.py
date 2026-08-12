class RequestError(Exception):
    """Base class for durable Request semantic failures."""


class RequestPayloadInvalid(RequestError):
    """Raised when caller payload does not satisfy the versioned Request schema."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"invalid Request payload at {path}: {reason}")
        self.path = path
        self.reason = reason


class UnsupportedRequestSchema(RequestError):
    """Raised when configured Request schema uses an unsupported keyword."""

    def __init__(self, path: str, keyword: str) -> None:
        super().__init__(f"unsupported Request schema keyword {keyword!r} at {path}")
        self.path = path
        self.keyword = keyword
