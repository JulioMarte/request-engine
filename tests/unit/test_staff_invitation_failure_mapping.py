"""Acceptance conflict classification is exact, never every unique violation."""

import json
from dataclasses import dataclass
from typing import NoReturn, cast
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.staff_invitation_commands import (
    PostgresStaffInvitationCommands,
)
from request_engine.modules.tenancy.api.staff_membership_errors import (
    staff_membership_error_handler,
)
from request_engine.modules.tenancy.application.errors import (
    StaffInvitationIdentityAlreadyLinked,
    StaffMembershipConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.unit, pytest.mark.security]


@dataclass(frozen=True)
class ConstraintDiagnostic:
    constraint_name: str


class ConstraintFailure(Exception):
    def __init__(self, constraint: str, sqlstate: str) -> None:
        self.diag = ConstraintDiagnostic(constraint)
        self.sqlstate = sqlstate


class FailingTransaction:
    def __init__(self, constraint: str, sqlstate: str) -> None:
        self.error = DBAPIError(
            "excluded unit persistence boundary", {}, ConstraintFailure(constraint, sqlstate)
        )

    def __call__(self) -> "FailingTransaction":
        return self

    def begin(self) -> "FailingTransaction":
        return self

    async def __aenter__(self) -> "FailingTransaction":
        return self

    async def __aexit__(self, *_arguments: object) -> None:
        return None

    async def execute(self, *_arguments: object, **_keywords: object) -> NoReturn:
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "constraint,sqlstate,linked",
    [
        ("principals_organization_id_principal_kind_external_subject_key", "23505", True),
        ("identity_bindings_tenant_subject_live_uq", "23505", True),
        ("staff_invitation_pending_email", "23505", False),
        ("staff_invitations_pkey", "23505", False),
        ("identity_bindings_tenant_subject_live_uq", "55000", False),
    ],
)
async def test_invitation_acceptance_only_classifies_existing_identity_constraints(
    constraint: str,
    sqlstate: str,
    linked: bool,
) -> None:
    writer = PostgresStaffInvitationCommands(
        cast(SessionFactory, FailingTransaction(constraint, sqlstate)),
        secret_delivery=None,
        delivery_recorder=None,
    )
    authenticated = AuthenticatedHttpSubject(
        AuthenticatedSubject(str(uuid4()), str(uuid4()), AuthenticatedSubjectClass.HUMAN),
        "native_session",
        str(uuid4()),
    )
    invitation_id = uuid4()
    with pytest.raises(
        StaffInvitationIdentityAlreadyLinked if linked else StaffMembershipConflict
    ) as failure:
        await writer.accept(authenticated, invitation_id, f"{invitation_id}.proof")
    response = await staff_membership_error_handler(Request({"type": "http"}), failure.value)
    assert response.status_code == 409
    error = json.loads(bytes(response.body))["error"]
    assert error["code"] == (
        "staff_invitation_identity_already_linked" if linked else "staff_membership_conflict"
    )
    assert error["retryable"] is False
    if linked:
        assert error["resolution"] == "request_authority"
        assert "existing membership and permissions" in error["message"]
        assert "resending an invitation will not restore access" in error["message"]
