from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.modules.catalog.application.commands import (
    configure_offering_version_booking_terms as terms_commands,
)
from request_engine.modules.catalog.application.errors import CatalogInvalidInput


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("1." + "0" * 16000, "1"), ("0." + "0" * 16000, "0"), ("0.123456" + "0" * 16000, "0.123456")],
)
def test_zero_padding_preserves_valid_exact_amount(amount: str, expected: str) -> None:
    # Real admission boundary, independent decimal literals; no timing-based oracle.
    command = terms_commands.ConfigureOfferingVersionBookingTermsCommand(
        uuid4(), uuid4(), uuid4(), uuid4(), Decimal(amount), "USD", "padded-valid"
    )
    terms_commands.validate_booking_terms_input(command)
    assert command.amount == Decimal(expected)


def test_zero_padding_cannot_hide_a_seventh_significant_fractional_digit() -> None:
    command = terms_commands.ConfigureOfferingVersionBookingTermsCommand(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        Decimal("0.1234567" + "0" * 16000),
        "USD",
        "padded-invalid",
    )
    with pytest.raises(CatalogInvalidInput, match="6 fractional digits"):
        terms_commands.validate_booking_terms_input(command)
