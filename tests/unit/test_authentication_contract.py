import pytest

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_authenticated_subject_separates_human_and_workload_identity() -> None:
    human = AuthenticatedSubject(
        authority_id="re-native",
        subject_id="user-123",
        subject_class=AuthenticatedSubjectClass.HUMAN,
    )
    workload = AuthenticatedSubject(
        authority_id="re-native-workload",
        subject_id="agent-credential-7",
        subject_class=AuthenticatedSubjectClass.WORKLOAD,
    )

    assert human.subject_class is AuthenticatedSubjectClass.HUMAN
    assert workload.subject_class is AuthenticatedSubjectClass.WORKLOAD


def test_authenticated_subject_contains_no_re_authority_fields() -> None:
    fields = set(AuthenticatedSubject.__dataclass_fields__)

    assert "organization_id" not in fields
    assert "principal_id" not in fields
    assert "capabilities" not in fields
    assert "delegation_id" not in fields
    assert "provider_role" not in fields


def test_authenticated_subject_rejects_blank_authority_or_subject() -> None:
    with pytest.raises(ValueError, match="authority_id"):
        AuthenticatedSubject(
            authority_id=" ",
            subject_id="subject",
            subject_class=AuthenticatedSubjectClass.HUMAN,
        )
    with pytest.raises(ValueError, match="subject_id"):
        AuthenticatedSubject(
            authority_id="native",
            subject_id=" ",
            subject_class=AuthenticatedSubjectClass.WORKLOAD,
        )
