import re

_PHONE_SEPARATORS = re.compile(r"[\s().-]+")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


def normalize_public_contact_value(channel: str, value: str) -> str:
    """Return the canonical value stored for a public operational endpoint."""

    cleaned = value.strip()
    if not cleaned:
        raise ValueError("normalized_value is required")
    if channel in {"phone", "whatsapp"}:
        canonical = _PHONE_SEPARATORS.sub("", cleaned)
        if not _E164.fullmatch(canonical):
            raise ValueError(f"{channel} must be an international E.164 number")
        return canonical
    if channel == "email":
        canonical = cleaned.casefold()
        if canonical.count("@") != 1 or any(char.isspace() for char in canonical):
            raise ValueError("email must contain one @ and no whitespace")
        local, domain = canonical.split("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must be a canonical address")
        return canonical
    raise ValueError("unsupported public contact channel")
