"""Default translators and the ``grant`` dispatcher (PRP-34 item 10).

The connector keeps ONE translator per target kind, but two items serve target kind ``grant``:
``budget_cap_change`` (item 4, :class:`~.cap.BudgetCapTranslator`) and ``grant_publish`` /
``grant_unpublish`` (item 5, :class:`~.grants.GrantPublicationTranslator`). Their diff grammars do
not overlap, so :class:`GrantDispatchTranslator` routes a request by its diff alone:

* publication grammar: every operation (``/plan_digest`` aside) is ``/publication`` or below it;
* cap grammar: every operation is one of ``/target/kind``, ``/counter_key``,
  ``/metric_namespace`` or below ``/limits/``.

A diff that touches both families is refused (``grant_diff_ambiguous``), one that touches neither
or carries any other path is refused (``grant_diff_unrecognised``): the dispatcher never guesses.
The chosen translator then applies its own full grammar.

:func:`default_translators` is what a production composition registers (the worker's
``build_apim_gateway_connector``): backend swaps, the grant dispatcher (cap naming aligned with
the publisher's fragment naming, publication checked against the apply-record store) and MCP
publication with the gateway's API path index.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from neurosphere_connector.write import WriteRequest
from neurosphere_core.errors import InvalidSchemaError

from neurosphere_connector_apim_gateway.arm import ApimArm
from neurosphere_connector_apim_gateway.cap import (
    GRANT_ENTITY_TYPE,
    AttributeChange,
    BudgetCapTranslator,
    grant_fragment_id,
)
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.grants import PUBLICATION_PATH, GrantPublicationTranslator
from neurosphere_connector_apim_gateway.mcp import ApiPathIndex, McpServerTranslator
from neurosphere_connector_apim_gateway.models import ResourceSpec
from neurosphere_connector_apim_gateway.records import ApplyRecordStore
from neurosphere_connector_apim_gateway.swap import BackendSwapTranslator
from neurosphere_connector_apim_gateway.translate import PLAN_DIGEST_PATH, IntentTranslator

__all__ = [
    "GRANT_DIFF_AMBIGUOUS",
    "GRANT_DIFF_UNRECOGNISED",
    "GrantDiffFamily",
    "GrantDispatchTranslator",
    "default_translators",
    "grant_diff_family",
]

GRANT_DIFF_AMBIGUOUS: Final = "grant_diff_ambiguous"
GRANT_DIFF_UNRECOGNISED: Final = "grant_diff_unrecognised"
_CAP_FACTS: Final = frozenset({"/target/kind", "/counter_key", "/metric_namespace"})
_LIMITS: Final = "/limits/"

GrantDiffFamily = Literal["cap", "publication"]


def _family_of(path: str) -> GrantDiffFamily | None:
    if path == PUBLICATION_PATH or path.startswith(PUBLICATION_PATH + "/"):
        return "publication"
    if path in _CAP_FACTS or path.startswith(_LIMITS):
        return "cap"
    return None


def grant_diff_family(request: WriteRequest) -> GrantDiffFamily:
    """Which grant grammar a diff uses; refuses an ambiguous or unrecognised diff."""
    families: set[GrantDiffFamily] = set()
    for op in request.proposed_diff.operations:
        if op.path == PLAN_DIGEST_PATH:
            continue
        family = _family_of(op.path)
        if family is None:
            raise InvalidSchemaError(
                "the grant diff matches neither the cap nor the publication grammar",
                reason=GRANT_DIFF_UNRECOGNISED,
            )
        families.add(family)
    if len(families) > 1:
        raise InvalidSchemaError(
            "the grant diff mixes the cap and the publication grammars",
            reason=GRANT_DIFF_AMBIGUOUS,
        )
    if not families:
        raise InvalidSchemaError("the grant diff names no change", reason=GRANT_DIFF_UNRECOGNISED)
    return next(iter(families))


class GrantDispatchTranslator:
    """The one ``IntentTranslator`` for target ``grant``: cap or publication by diff grammar."""

    def __init__(
        self,
        *,
        cap: BudgetCapTranslator | None = None,
        publication: GrantPublicationTranslator | None = None,
    ) -> None:
        self.cap = cap if cap is not None else BudgetCapTranslator(fragment_id=grant_fragment_id)
        self.publication = publication if publication is not None else GrantPublicationTranslator()

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({GRANT_ENTITY_TYPE})

    def route(self, request: WriteRequest) -> BudgetCapTranslator | GrantPublicationTranslator:
        return self.cap if grant_diff_family(request) == "cap" else self.publication

    def check_kind(self, action_kind: str, request: WriteRequest) -> None:
        self.route(request).check_kind(action_kind, request)

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        return await self.route(request).current_version(arm, gateway, request)

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        return self.route(request).specs(gateway, request)

    async def preview(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> list[AttributeChange]:
        """The cap's before/after attribute diff; a publication has no attribute preview."""
        translator = self.route(request)
        if not isinstance(translator, BudgetCapTranslator):
            return []
        return await translator.preview(arm, gateway, request)


def default_translators(
    *,
    records: ApplyRecordStore | None,
    paths: ApiPathIndex | None,
    **swap_options: Any,
) -> list[IntentTranslator]:
    """The translators a production APIM connector registers (beyond the generic one).

    ``records`` must be the connector's own apply-record store (an unpublish is checked against
    it); ``paths`` lists the gateway's API paths (``HttpApiPathIndex``); without it an MCP
    publication is refused (``mcp_api_paths_unreadable``), never guessed.
    """
    return [
        BackendSwapTranslator(**swap_options),
        GrantDispatchTranslator(
            cap=BudgetCapTranslator(fragment_id=grant_fragment_id),
            publication=GrantPublicationTranslator(records=records),
        ),
        McpServerTranslator(paths=paths),
    ]
