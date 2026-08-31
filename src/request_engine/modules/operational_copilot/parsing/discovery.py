from request_engine.modules.operational_copilot.contracts import (
    CopilotIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
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

_PUBLISH = compile_pattern(
    rf"publish offering (?P<offering>{UUID_PATTERN}) at location (?P<location>{UUID_PATTERN}) "
    rf"for discovery starting (?P<start>{DATETIME_PATTERN})"
    rf"(?: ending (?P<end>{DATETIME_PATTERN}))?"
    rf"(?: with resource (?P<resource>{UUID_PATTERN}))?"
    r"(?: visibility (?P<visibility>\S+))?"
)
_REVOKE = compile_pattern(
    rf"revoke discovery publication (?P<publication>{UUID_PATTERN}) "
    rf"at revision (?P<revision>{UINT_PATTERN})"
)


def parse_discovery_intent(text: str) -> CopilotIntent | None:
    publish = _PUBLISH.fullmatch(text)
    if publish is not None:
        end = publish.group("end")
        resource = publish.group("resource")
        return PublishDiscoverySupplyIntent(
            offering_id=parse_uuid(publish.group("offering")),
            location_id=parse_uuid(publish.group("location")),
            effective_start=parse_datetime(publish.group("start")),
            effective_end=parse_datetime(end) if end is not None else None,
            resource_id=parse_uuid(resource) if resource is not None else None,
            provider_visibility=(
                publish.group("visibility").casefold()
                if publish.group("visibility") is not None
                else "hidden"
            ),
        )

    revoke = _REVOKE.fullmatch(text)
    if revoke is not None:
        return RevokeDiscoveryPublicationIntent(
            publication_id=parse_uuid(revoke.group("publication")),
            expected_revision=parse_uint(revoke.group("revision")),
        )

    return None
