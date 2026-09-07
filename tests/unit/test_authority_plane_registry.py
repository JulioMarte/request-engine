from request_engine.platform.security.capabilities import (
    AuthorityPlane,
    capability_definition,
    canonical_capability_keys,
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
    }

    assert platform | tenant_control <= canonical_capability_keys()
    assert {_plane(key) for key in platform} == {AuthorityPlane.PLATFORM}
    assert {_plane(key) for key in tenant_control} == {AuthorityPlane.TENANT_CONTROL}
    assert _plane("appointments.book") is AuthorityPlane.OPERATIONAL


def test_authority_planes_do_not_create_implicit_capability_implication() -> None:
    assert not grant_satisfies("organization.provision", "staff.manage_authority")
    assert not grant_satisfies("organization.provision", "appointments.book")
    assert not grant_satisfies("staff.manage_authority", "appointments.book")
    assert not grant_satisfies("appointments.book", "staff.manage_authority")


def test_control_capabilities_are_not_runtime_discoverable_before_surfaces_exist() -> None:
    for key in (
        "platform.principal.provision",
        "organization.provision",
        "staff.manage_authority",
        "agent.provision",
        "identity.bind",
    ):
        definition = capability_definition(key)
        assert definition is not None
        assert definition.runtime_available is False
        assert definition.discoverable is False
