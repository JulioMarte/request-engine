"""Subject-kind compatibility for strong Party identifiers."""

from request_engine.modules.tenancy.contracts.party_kind import PartyKind

_PERSON_DOCUMENTS = frozenset({"cedula", "passport"})
_ORGANIZATION_DOCUMENTS = frozenset({"rnc"})


def party_kind_for_document(kind: str) -> PartyKind:
    if kind in _PERSON_DOCUMENTS:
        return PartyKind.PERSON
    if kind in _ORGANIZATION_DOCUMENTS:
        return PartyKind.ORGANIZATION
    raise ValueError(f"unsupported strong identifier kind: {kind}")


def require_document_party_kind(party_kind: PartyKind | str, document_kind: str) -> None:
    expected = party_kind_for_document(document_kind)
    actual = PartyKind(party_kind)
    if actual is not expected:
        raise ValueError(f"{document_kind} identifies a {expected.value} Party, not {actual.value}")
