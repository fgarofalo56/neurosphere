"""Reconciliation view API (PRP-14 item 4): gateway, app and billing against the ledger reference.

``GET /api/v1/reconciliation/domains/{domain}?days=1..90`` reads ONLY item 1's reconciliation
rollups through ``neurosphere_core.aggregates.AggregateReader`` (never the ledger or the analytics
adapter), so it keeps working when either is down.

Response shape (the PRP-14 wire contract, with per-currency detail added within it):

* ``reference``: the ledger amount, each request counted once. Populated when exactly one currency
  bucket exists; otherwise its amount is ``unknown`` (currencies are never added). ``references``
  carries one entry per currency (``currency: null`` is the undeterminable-currency bucket) with
  ``entry_count`` and ``unknown_entry_count``.
* ``sources``: ONE entry per (source, currency), in currency then gateway/app/billing order, each
  with ``granularity`` (``request`` | ``vendor`` | ``unknown`` as item 1 recorded it), ``amount``,
  ``coverage`` and ``variance`` (= source minus reference; unknown if either side is unknown). A
  source that reported nothing has ``coverage.status: "unknown"``, never 0.
* ``unknown_remainder``: a COUNT (``unit: "entries"``) of ledger entries whose amount is unknown
  (their money value is unknowable). Unknown when several currency buckets exist, because the
  undeterminable-currency bucket is shared by all of them.
* ``disclaimer``: always ``not_all_spend_observable``. Request-less vendor/period allocations feed
  only the billing source (``vendor`` granularity) and are NOT in the reference, so billing
  variance can be non-zero for that reason alone; no total claims all spend is observable.

Money in the body is a JSON number per the contract; sums and variance are computed in ``Decimal``.

Wiring (item 5): ``register(registry)`` and ``app.state.aggregate_reader``.
"""

from neurosphere_api.reconciliation.dependencies import READER_STATE_KEY, get_now, get_reader
from neurosphere_api.reconciliation.router import PREFIX, build_router, register

__all__ = ["PREFIX", "READER_STATE_KEY", "build_router", "get_now", "get_reader", "register"]
