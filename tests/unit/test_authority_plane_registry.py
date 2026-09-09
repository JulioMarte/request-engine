from request_engine.platform.security.capabilities import (
    AuthorityPlane,
    CapabilityExposure,
    RevisionPolicy,
    canonical_capability_keys,
    capability_definition,
    grant_satisfies,
)


def _plane(key: str) -> AuthorityPlane:
    definition = capability_definition(key)
    assert definition is not None
    return definition.authority_plane


def test_normative_identity_authority_capabilities_are_registered_by_plane() -> None:
    platform = {
        "platform.principal.provision",
        "platform.tenant_provisioner.provision",
        "organization.provision",
        "platform.identity.recover",
    }
    tenant_control = {
        "staff.invite",
        "staff.manage_membership",
        "staff.manage_authority",
        "agent.provision",
        "agent.manage_authority",
        "agent.suspend",
        "identity.bind",
        "platform.acting_for_operator",
    }

    assert platform | tenant_control <= canonical_capability_keys()
    assert {_plane(key) for key in platform} == {AuthorityPlane.PLATFORM}
    assert {_plane(key) for key in tenant_control} == {AuthorityPlane.TENANT_CONTROL}
    assert _plane("appointments.book") is AuthorityPlane.OPERATIONAL


def test_legacy_platform_prefix_does_not_promote_tenant_relay_to_platform_authority() -> None:
    assert _plane("platform.acting_for_operator") is AuthorityPlane.TENANT_CONTROL
    assert _plane("platform.principal.provision") is AuthorityPlane.PLATFORM


def test_authority_planes_do_not_create_implicit_capability_implication() -> None:
    assert not grant_satisfies("organization.provision", "staff.manage_authority")
    assert not grant_satisfies("organization.provision", "appointments.book")
    assert not grant_satisfies("staff.manage_authority", "appointments.book")
    assert not grant_satisfies("appointments.book", "staff.manage_authority")


def test_staff_lifecycle_capabilities_are_runtime_operator_surfaces() -> None:
    expected_revision = {
        "staff.invite": RevisionPolicy.NONE,
        "staff.manage_membership": RevisionPolicy.REQUIRED,
        "staff.manage_authority": RevisionPolicy.REQUIRED,
    }
    for key, revision in expected_revision.items():
        definition = capability_definition(key)
        assert definition is not None
        assert definition.runtime_available is True
        assert definition.discoverable is True
        assert definition.exposure is CapabilityExposure.OPERATOR
        assert definition.revision is revision


def test_agent_lifecycle_capabilities_are_runtime_operator_surfaces() -> None:
    for key in ("agent.provision", "agent.manage_authority", "agent.suspend"):
        definition = capability_definition(key)
        assert definition is not None
        assert definition.runtime_available is True
        assert definition.exposure is CapabilityExposure.OPERATOR


def test_unimplemented_control_capabilities_remain_internal_and_nonruntime() -> None:
    for key in (
        "platform.principal.provision",
        "organization.provision",
        "identity.bind",
    ):
        definition = capability_definition(key)
        assert definition is not None
        assert definition.runtime_available is False
        assert definition.discoverable is False
