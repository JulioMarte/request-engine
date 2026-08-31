import re
from datetime import datetime
from uuid import UUID

from request_engine.modules.operational_copilot.errors import UnsupportedCopilotIntent

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
UINT_PATTERN = r"[0-9]+"
DATETIME_PATTERN = r"\S+"


def parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise UnsupportedCopilotIntent(f"invalid identifier: {value}") from error


def parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise UnsupportedCopilotIntent(f"invalid datetime: {value}") from error


def parse_uint(value: str) -> int:
    return int(value)


def compile_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)
