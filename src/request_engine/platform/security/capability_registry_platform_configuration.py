from request_engine.platform.security.capability_types import (
    AuthorityPlane,
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)
from request_engine.platform.security.operation_risk import OperationRiskClass


def _platform_command(
    key: str,
    description: str,
    *,
    revision: RevisionPolicy = RevisionPolicy.REQUIRED,
    runtime_available: bool = False,
) -> CapabilityDefinition:
    return command_capability(
        key,
        CapabilityExposure.OPERATOR,
        description,
        authority_plane=AuthorityPlane.PLATFORM,
        revision=revision,
        runtime_available=runtime_available,
        risk_class=OperationRiskClass.AUTHORITY_CHANGE,
        requires_recent_authentication=True,
    )


PLATFORM_CONFIGURATION_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "platform.configuration.read",
        CapabilityExposure.OPERATOR,
        "Read governed platform configuration metadata and revisions.",
        authority_plane=AuthorityPlane.PLATFORM,
        runtime_available=True,
    ),
    _platform_command(
        "platform.configuration.stage",
        "Stage a typed platform configuration revision.",
        revision=RevisionPolicy.SERVER_SELECTED,
        runtime_available=True,
    ),
    _platform_command(
        "platform.configuration.validate",
        "Validate an exact staged platform configuration revision.",
        runtime_available=True,
    ),
    _platform_command(
        "platform.configuration.activate",
        "Activate an exact validated platform configuration revision.",
        runtime_available=True,
    ),
    _platform_command(
        "platform.configuration.disable",
        "Disable an exact platform configuration revision.",
        runtime_available=True,
    ),
    _platform_command(
        "platform.secret.write",
        "Create governed platform secret material and binding metadata.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
    _platform_command(
        "platform.secret.rotate",
        "Rotate an exact governed platform secret binding.",
    ),
    _platform_command(
        "platform.secret.revoke",
        "Revoke an exact governed platform secret binding.",
    ),
    _platform_command(
        "platform.provider.test",
        "Test an exact governed provider configuration revision.",
    ),
    query_capability(
        "platform.readiness.read",
        CapabilityExposure.OPERATOR,
        "Read the diagnostic platform operational-readiness projection.",
        authority_plane=AuthorityPlane.PLATFORM,
        runtime_available=False,
    ),
)
