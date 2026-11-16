"""The three detection rules (PRP-61 item 2).

Each rule reads through a protocol, never a service, and answers with a :class:`RuleResult`:
findings plus an honest coverage status. A read that failed is ``unknown`` and emits nothing;
a rule with nothing declared to compare against is ``not_evaluated``. A finding says the
configuration differs from the declared expectation; it never says a deployment is safe.
"""

from __future__ import annotations

from collections.abc import Iterable

from neurosphere_core.detections.models import (
    CROSS_CLOUD_REASON,
    KIND_CONFIGURATION_FINDING,
    KIND_UNREGISTERED_AI_RESOURCE,
    RULE_CONTENT_FILTER,
    RULE_CONTENT_FILTER_UNSET_ONLY,
    RULE_GATEWAY_FRAGMENT,
    RULE_SHADOW_AI,
    RULE_VERSION,
    AccountRead,
    AiAccountInventory,
    CatalogDeploymentReader,
    CoverageStatus,
    DeploymentConfigReader,
    Finding,
    GatewayInventoryReader,
    GatewayRead,
    ReadStatus,
    RuleResult,
    digest,
    opaque,
    segment,
)

__all__ = ["ContentFilterRule", "GatewayFragmentRule", "ShadowAiRule"]

MAX_TAG_KEYS = 20
UNSET = "unset"


def _normalise(names: Iterable[str]) -> frozenset[str]:
    return frozenset(n.strip().lower() for n in names if n and n.strip())


def _status_coverage(status: ReadStatus, reason: str | None) -> tuple[CoverageStatus, str]:
    if status == "capability_unavailable":
        return CoverageStatus.CAPABILITY_UNAVAILABLE, reason or "capability_unavailable"
    if status == "cross_cloud":
        return CoverageStatus.UNKNOWN, reason or CROSS_CLOUD_REASON
    return CoverageStatus.UNKNOWN, reason or "read_failed"


class ContentFilterRule:
    """A Foundry deployment has no content-filter policy, or one outside the acceptable list."""

    def __init__(
        self,
        *,
        cloud: str,
        customer_id: str,
        reader: DeploymentConfigReader,
        acceptable_policies: Iterable[str] = (),
    ) -> None:
        self._cloud = cloud
        self._customer = customer_id
        self._reader = reader
        self._acceptable = _normalise(acceptable_policies)
        self.rule_id = RULE_CONTENT_FILTER if self._acceptable else RULE_CONTENT_FILTER_UNSET_ONLY

    async def evaluate(self) -> RuleResult:
        try:
            reads = list(await self._reader.read())
        except Exception:
            return RuleResult(self.rule_id, CoverageStatus.UNKNOWN, "read_failed")
        if not reads:
            return RuleResult(self.rule_id, CoverageStatus.NOT_EVALUATED, "no_accounts_configured")
        findings: list[Finding] = []
        unknown = skipped = 0
        truncated = False
        unavailable: list[str] = []
        for read in reads:
            if read.status != "ok":
                unknown += 1
                if read.status == "capability_unavailable":
                    unavailable.append(read.account)
                continue
            truncated = truncated or read.truncated
            for dep in read.deployments:
                subject_name = segment(dep.name)
                if subject_name is None:
                    skipped += 1
                    continue
                policy = (dep.rai_policy or "").strip()
                observed = UNSET if not policy else policy.lower()
                if observed != UNSET and (not self._acceptable or observed in self._acceptable):
                    continue
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        rule_version=RULE_VERSION,
                        kind=KIND_CONFIGURATION_FINDING,
                        subject_id=(
                            f"{self._cloud}:{self._customer}:foundry:model_deployment:"
                            f"{subject_name}"
                        ),
                        observed=observed,
                        evidence=(
                            opaque("rai_policy=", observed),
                            opaque("account=", dep.account),
                        ),
                        coverage="partial" if read.truncated else "full",
                    )
                )
        if unknown == len(reads):
            if unavailable and len(unavailable) == len(reads):
                coverage = CoverageStatus.CAPABILITY_UNAVAILABLE
                reason = "capability_unavailable"
            else:
                coverage, reason = CoverageStatus.UNKNOWN, "read_failed"
            return RuleResult(
                self.rule_id, coverage, reason, unknown_targets=unknown, skipped_invalid=skipped
            )
        partial = unknown > 0 or truncated
        return RuleResult(
            self.rule_id,
            CoverageStatus.PARTIAL if partial else CoverageStatus.FULL,
            "partial_read" if partial else None,
            tuple(findings),
            truncated=truncated,
            unknown_targets=unknown,
            skipped_invalid=skipped,
        )


class GatewayFragmentRule:
    """A registered gateway's latest inventory lacks a required policy-fragment name."""

    def __init__(
        self,
        *,
        cloud: str,
        customer_id: str,
        reader: GatewayInventoryReader,
        required_fragments: Iterable[str] = (),
    ) -> None:
        self._cloud = cloud
        self._customer = customer_id
        self._reader = reader
        self._required = _normalise(required_fragments)
        self.rule_id = RULE_GATEWAY_FRAGMENT

    async def evaluate(self) -> RuleResult:
        if not self._required:
            return RuleResult(self.rule_id, CoverageStatus.NOT_EVALUATED, "no_required_fragments")
        try:
            read: GatewayRead = await self._reader.read()
        except Exception:
            return RuleResult(self.rule_id, CoverageStatus.UNKNOWN, "read_failed")
        if read.status != "ok":
            coverage, reason = _status_coverage(read.status, read.reason)
            return RuleResult(self.rule_id, coverage, reason)
        findings: list[Finding] = []
        unknown = skipped = 0
        for gw in read.gateways:
            name = segment(gw.gateway_id)
            if name is None:
                skipped += 1
                continue
            if "policy_fragments" in gw.unreadable_lists:
                unknown += 1
                continue
            missing = sorted(self._required - _normalise(gw.fragment_names))
            if not missing:
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    rule_version=RULE_VERSION,
                    kind=KIND_CONFIGURATION_FINDING,
                    subject_id=f"{self._cloud}:{self._customer}:apim:gateway:{name}",
                    observed="missing=" + ",".join(missing),
                    evidence=tuple(opaque("missing_fragment=", m) for m in missing),
                    coverage="partial" if read.truncated else "full",
                    domain_id=gw.domain_id,
                )
            )
        partial = unknown > 0 or read.truncated
        return RuleResult(
            self.rule_id,
            CoverageStatus.PARTIAL if partial else CoverageStatus.FULL,
            "partial_read" if partial else None,
            tuple(findings),
            truncated=read.truncated,
            unknown_targets=unknown,
            skipped_invalid=skipped,
        )


class ShadowAiRule:
    """An AI account Resource Graph shows that no catalog entity or configured target names.

    Matching (documented in the runbook): an account is *known* when its name, case-insensitive,
    equals the resource part of a catalog ``model_deployment``'s ``foundry_project`` attribute
    (``resource/project``) or a configured account or discovery-target resource name.
    """

    def __init__(
        self,
        *,
        cloud: str,
        customer_id: str,
        inventory: AiAccountInventory,
        catalog: CatalogDeploymentReader,
        configured_accounts: Iterable[str] = (),
    ) -> None:
        self._cloud = cloud
        self._customer = customer_id
        self._inventory = inventory
        self._catalog = catalog
        self._configured = _normalise(configured_accounts)
        self.rule_id = RULE_SHADOW_AI

    async def evaluate(self) -> RuleResult:
        try:
            accounts: AccountRead = await self._inventory.read()
        except Exception:
            return RuleResult(self.rule_id, CoverageStatus.UNKNOWN, "read_failed")
        if accounts.status != "ok":
            coverage, reason = _status_coverage(accounts.status, accounts.reason)
            return RuleResult(self.rule_id, coverage, reason)
        try:
            catalog = await self._catalog.read()
        except Exception:
            return RuleResult(self.rule_id, CoverageStatus.UNKNOWN, "catalog_read_failed")
        if not catalog.ok or catalog.truncated:
            # An incomplete "known" set would turn registered accounts into false findings.
            reason = catalog.reason or ("catalog_truncated" if catalog.truncated else None)
            return RuleResult(
                self.rule_id,
                CoverageStatus.UNKNOWN,
                reason or "catalog_read_failed",
                truncated=catalog.truncated,
            )
        known = self._configured | {
            p.split("/", 1)[0].strip().lower() for p in catalog.projects if p.strip()
        }
        findings: list[Finding] = []
        skipped = 0
        for acct in accounts.accounts:
            name = segment(acct.name)
            if name is None:
                skipped += 1
                continue
            if name in known:
                continue
            tags = tuple(sorted({t.strip().lower() for t in acct.tag_keys if t.strip()}))
            ident = digest(acct.resource_id)
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    rule_version=RULE_VERSION,
                    kind=KIND_UNREGISTERED_AI_RESOURCE,
                    subject_id=(
                        f"{self._cloud}:{self._customer}:azure_resource_graph:ai_account:"
                        f"{name}-{ident[:8]}"
                    ),
                    observed=f"arm_sha256={ident}",
                    evidence=(
                        opaque("arm_sha256=", ident),
                        opaque("location=", acct.location),
                        *(opaque("tag_key=", t) for t in tags[:MAX_TAG_KEYS]),
                    ),
                    coverage="partial" if accounts.truncated else "full",
                )
            )
        return RuleResult(
            self.rule_id,
            CoverageStatus.PARTIAL if accounts.truncated else CoverageStatus.FULL,
            "inventory_truncated" if accounts.truncated else None,
            tuple(findings),
            truncated=accounts.truncated,
            skipped_invalid=skipped,
        )
