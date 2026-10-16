"""Estimated and invoiced stay distinct; unknown stays null; currencies never mix."""

from __future__ import annotations

from decimal import Decimal

from neurosphere_core.ledger import fold_entry

from .builders import CATEGORY, CUSTOMER, REQUEST, application, billing, gateway


def _fold(*items):  # type: ignore[no-untyped-def]
    return fold_entry(CUSTOMER, REQUEST, CATEGORY, items)


def test_distinct_fields_are_never_summed_or_substituted() -> None:
    entry = _fold(gateway(1, "1.00"), billing(2, "1.20"))
    assert entry.estimated_amount == Decimal("1.00")
    assert entry.invoiced_amount == Decimal("1.20")
    assert entry.authoritative_amount == Decimal("1.20")


def test_estimate_only_leaves_invoiced_null() -> None:
    entry = _fold(gateway(1, "1.00"))
    assert entry.invoiced_amount is None  # not 0, not the estimate
    assert entry.estimated_amount == Decimal("1.00")
    assert entry.authoritative_kind == "estimated"


def test_invoice_only_leaves_estimated_null() -> None:
    entry = _fold(billing(1, "1.20"))
    assert entry.estimated_amount is None
    assert entry.invoiced_amount == Decimal("1.20")


def test_unknown_invoice_does_not_become_the_estimate() -> None:
    entry = _fold(gateway(1, "1.00"), billing(2, None))
    assert entry.invoiced_amount is None  # still unknown
    assert entry.estimated_amount == Decimal("1.00")
    # The only known amount is the estimate; the source names it, so it is never mistaken for an
    # invoice.
    assert (entry.authoritative_source, entry.authoritative_kind) == ("gateway", "estimated")


def test_unknown_estimate_does_not_become_the_invoice() -> None:
    entry = _fold(gateway(1, None), billing(2, "1.20"))
    assert entry.estimated_amount is None
    assert entry.invoiced_amount == Decimal("1.20")


def test_everything_unknown_is_null_not_zero() -> None:
    entry = _fold(gateway(1, None), application(2, None))
    assert entry.authoritative_amount is None
    assert entry.estimated_amount is None and entry.invoiced_amount is None


def test_retry_and_allocation_are_separate_fields_not_added() -> None:
    from neurosphere_core.ledger import AllocationParts

    entry = _fold(
        gateway(
            1,
            "2.00",
            retry_count=1,
            retry_amount=Decimal("0.50"),
            allocation=AllocationParts(ptu=Decimal("1.00")),
        )
    )
    assert entry.authoritative_amount == Decimal("2.00")
    assert entry.retry_count == 1 and entry.retry_amount == Decimal("0.50")
    assert entry.allocation is not None and entry.allocation.ptu == Decimal("1.00")
    assert entry.allocation.compute is None  # unknown, not 0


def test_mixed_currencies_in_one_source_are_unknown_and_flagged() -> None:
    entry = _fold(gateway(1, "1.00", currency="USD"), gateway(2, "1.00", currency="EUR"))
    assert entry.authoritative_amount is None
    assert entry.currency_conflict
    assert entry.authoritative_currency is None


def test_serialization_is_plain_decimal_strings() -> None:
    entry = _fold(gateway(1, "0.0000001"))
    dumped = entry.model_dump(mode="json")
    assert dumped["authoritative_amount"] == "0.000000100000"
    assert "E" not in dumped["authoritative_amount"]
    assert entry.model_validate(dumped) == entry
