from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane


def validate_staff_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    """Validate the canonical authority vocabulary accepted by Staff commands/plans."""

    if len(set(capabilities)) != len(capabilities):
        raise ValueError("desired_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane not in {
            AuthorityPlane.TENANT_CONTROL,
            AuthorityPlane.OPERATIONAL,
        }:
            raise ValueError(f"capability is not tenant authority: {capability}")
    return tuple(sorted(capabilities))
