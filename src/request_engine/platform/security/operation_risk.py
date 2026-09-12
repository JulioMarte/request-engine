from __future__ import annotations

from enum import StrEnum


class OperationRiskClass(StrEnum):
    """Risk classification for agent-executable operations.

    Severity increases with list order. AUTHORITY_CHANGE is banned outright
    for agent execution regardless of any policy risk ceiling.
    """

    READ = "read"
    LOW_IMPACT_WRITE = "low_impact_write"
    REVERSIBLE_WRITE = "reversible_write"
    EXTERNAL_COMMITMENT = "external_commitment"
    SENSITIVE_DATA = "sensitive_data"
    FINANCIAL = "financial"
    DESTRUCTIVE = "destructive"
    AUTHORITY_CHANGE = "authority_change"


RISK_SEVERITY_ORDER: tuple[OperationRiskClass, ...] = (
    OperationRiskClass.READ,
    OperationRiskClass.LOW_IMPACT_WRITE,
    OperationRiskClass.REVERSIBLE_WRITE,
    OperationRiskClass.EXTERNAL_COMMITMENT,
    OperationRiskClass.SENSITIVE_DATA,
    OperationRiskClass.FINANCIAL,
    OperationRiskClass.DESTRUCTIVE,
    OperationRiskClass.AUTHORITY_CHANGE,
)


def risk_severity(risk: OperationRiskClass) -> int:
    """Return the comparable severity of one risk class."""

    return RISK_SEVERITY_ORDER.index(risk)


__all__ = ["RISK_SEVERITY_ORDER", "OperationRiskClass", "risk_severity"]
