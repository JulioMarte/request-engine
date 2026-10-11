"""Lossless decimal transport admission, independent of monetary business policy."""

from decimal import Decimal


def admit_exact_decimal(value: object) -> object:
    """JSON fractions become floats before DTO validation; never admit that loss."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("decimal input must be an exact decimal string or integer")
    return value
