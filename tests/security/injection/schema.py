"""Case schema for the shared prompt-injection and overscope corpus (PRP-12 item 4).

A case is transport-neutral: it describes what a caller (or content the system reads) says, the
server-side request the adversarial input is trying to cause (``attempt``), the scope the server
derived for the caller, and the only acceptable outcome. Consumers (PRP-19 copilot, PRP-22 MCP)
translate a case into their own transport inside an adapter; the case itself never names one.

Outcome semantics:

* ``deny``: the attempt reaches an authorization or policy decision and is refused (out-of-scope
  retrieval, unregistered tool or argument, banned chart construct, non-allowlisted egress, raw
  query language, secret disclosure, claimed privilege).
* ``abstain``: the attempt only asks the assistant to change its own behaviour or claims; the
  assistant declines to follow the embedded instruction and does not fabricate an answer.

Every model is ``extra="forbid"`` and frozen, so a typo in ``corpus.json`` fails loading.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from neurosphere_core.auth.scope import Permission, Role, role_permissions
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

CORPUS_PATH: Final = Path(__file__).with_name("corpus.json")

CaseId = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$", max_length=96)]
DomainId = Annotated[
    str,
    Field(pattern=r"^(commercial|government):[a-z0-9-]+:catalog:domain:[a-z0-9-]+$"),
]
NonEmpty = Annotated[str, Field(min_length=1, max_length=4000)]

ExpectedOutcome = Literal["abstain", "deny"]
Vector = Literal["direct", "indirect"]
Channel = Literal["retrieved_doc", "tool_output", "catalog_metadata", "tool_manifest"]


class Category(StrEnum):
    DIRECT_INJECTION = "direct_injection"
    INDIRECT_RETRIEVED_DOC = "indirect_injection_retrieved_doc"
    INDIRECT_TOOL_OUTPUT = "indirect_injection_tool_output"
    INDIRECT_CATALOG_METADATA = "indirect_injection_catalog_metadata"
    OVERSCOPE_RETRIEVAL = "overscope_retrieval"
    SCOPE_SMUGGLING = "scope_smuggling"
    TOOL_MANIFEST_POISONING = "tool_manifest_poisoning"
    CHART_PLAN_EXFILTRATION = "chart_plan_exfiltration"
    ARBITRARY_QUERY = "arbitrary_query"
    SSRF = "ssrf"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    SECRET_EXFILTRATION = "secret_exfiltration"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopeFixture(StrictModel):
    """The scope the SERVER derived for the caller. Adapters build their real scope from this.

    Anything scope-shaped inside ``input`` or ``attempt`` is attacker-controlled and must be
    ignored; only this fixture describes what the caller may reach.
    """

    name: CaseId
    principal_id: Annotated[str, Field(pattern=r"^principal:[a-z0-9-]+:[a-z0-9-]+$")]
    customer_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    cloud: Literal["commercial", "government"] = "commercial"
    domain_ids: tuple[DomainId, ...] = Field(min_length=1, max_length=8)
    roles: tuple[Role, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def _domains_belong_to_scope(self) -> Self:
        for domain_id in self.domain_ids:
            cloud, customer = domain_id.split(":")[:2]
            if cloud != self.cloud or customer != self.customer_id:
                raise ValueError(f"{domain_id} is outside {self.cloud}/{self.customer_id}")
        return self

    def permissions(self) -> frozenset[Permission]:
        """Union of role permissions; roles apply to every domain in ``domain_ids``."""
        out: set[Permission] = set()
        for role in self.roles:
            out |= role_permissions(role)
        return frozenset(out)


class InjectedContent(StrictModel):
    """Untrusted content the system reads while serving the turn (never an instruction source)."""

    channel: Channel
    source_id: Annotated[str, Field(min_length=1, max_length=200)]
    text: NonEmpty


class CaseInput(StrictModel):
    user_turn: NonEmpty | None = None
    injected: tuple[InjectedContent, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if self.user_turn is None and not self.injected:
            raise ValueError("a case needs a user turn, injected content, or both")
        return self


# --- attempts: the server-visible request the adversarial input tries to cause ---------------


class FollowInstruction(StrictModel):
    kind: Literal["follow_instruction"]
    instruction: NonEmpty


class Retrieve(StrictModel):
    kind: Literal["retrieve"]
    target_domain_id: DomainId
    permission: Permission = Permission.DATA_READ
    resource_id: str | None = None


class ToolCall(StrictModel):
    kind: Literal["tool_call"]
    tool: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class RenderChart(StrictModel):
    kind: Literal["render_chart"]
    spec: dict[str, JsonValue]


class FetchUrl(StrictModel):
    kind: Literal["fetch_url"]
    url: NonEmpty
    redirects_to: tuple[NonEmpty, ...] = ()


class RunQuery(StrictModel):
    kind: Literal["run_query"]
    language: Literal["sql", "cypher", "kql", "javascript"]
    text: NonEmpty


class Reveal(StrictModel):
    kind: Literal["reveal"]
    target: Literal["system_prompt", "secret", "tool_credentials", "other_principal_history"]


class Escalate(StrictModel):
    kind: Literal["escalate"]
    claimed_role: Role
    permission: Permission
    target_domain_id: DomainId


Attempt = Annotated[
    FollowInstruction | Retrieve | ToolCall | RenderChart | FetchUrl | RunQuery | Reveal | Escalate,
    Field(discriminator="kind"),
]

#: Which attempt kinds a category may use. Indirect categories may carry any attempt: the
#: category names the channel, the attempt names what the planted content asks for.
_ANY: Final = frozenset(
    {
        "follow_instruction",
        "retrieve",
        "tool_call",
        "render_chart",
        "fetch_url",
        "run_query",
        "reveal",
        "escalate",
    }
)
CATEGORY_ATTEMPTS: Final[dict[Category, frozenset[str]]] = {
    Category.DIRECT_INJECTION: frozenset({"follow_instruction"}),
    Category.INDIRECT_RETRIEVED_DOC: _ANY,
    Category.INDIRECT_TOOL_OUTPUT: _ANY,
    Category.INDIRECT_CATALOG_METADATA: _ANY,
    Category.OVERSCOPE_RETRIEVAL: frozenset({"retrieve"}),
    Category.SCOPE_SMUGGLING: frozenset({"retrieve", "tool_call"}),
    Category.TOOL_MANIFEST_POISONING: frozenset({"tool_call", "follow_instruction"}),
    Category.CHART_PLAN_EXFILTRATION: frozenset({"render_chart"}),
    Category.ARBITRARY_QUERY: frozenset({"run_query"}),
    Category.SSRF: frozenset({"fetch_url"}),
    Category.PRIVILEGE_ESCALATION: frozenset({"escalate"}),
    Category.SECRET_EXFILTRATION: frozenset({"reveal"}),
}

#: Categories that are defined by the channel the injected content arrived on.
CATEGORY_CHANNEL: Final[dict[Category, Channel]] = {
    Category.INDIRECT_RETRIEVED_DOC: "retrieved_doc",
    Category.INDIRECT_TOOL_OUTPUT: "tool_output",
    Category.INDIRECT_CATALOG_METADATA: "catalog_metadata",
    Category.TOOL_MANIFEST_POISONING: "tool_manifest",
}


class InjectionCase(StrictModel):
    id: CaseId
    category: Category
    vector: Vector
    input: CaseInput
    attempt: Attempt
    expected: ExpectedOutcome
    scope: ScopeFixture
    rationale: Annotated[str, Field(min_length=10, max_length=600)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.vector == "direct" and self.input.user_turn is None:
            raise ValueError("a direct case carries the payload in input.user_turn")
        if self.vector == "indirect" and not self.input.injected:
            raise ValueError("an indirect case carries the payload in input.injected")
        if self.attempt.kind not in CATEGORY_ATTEMPTS[self.category]:
            raise ValueError(f"attempt {self.attempt.kind!r} does not fit {self.category}")
        channel = CATEGORY_CHANNEL.get(self.category)
        if channel is not None:
            if self.vector != "indirect":
                raise ValueError(f"{self.category} is an indirect category")
            if channel not in {c.channel for c in self.input.injected}:
                raise ValueError(f"{self.category} needs injected content on {channel!r}")
        return self

    def as_text(self) -> str:
        """The whole case as one JSON string (content-policy scans read this)."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)


class CorpusFile(StrictModel):
    """On-disk shape: named scope fixtures plus cases that reference one by name."""

    version: Literal[1]
    scope_fixtures: dict[str, dict[str, JsonValue]]
    cases: list[dict[str, JsonValue]]


_REF: Final = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def load_corpus(path: Path = CORPUS_PATH) -> tuple[InjectionCase, ...]:
    """Load and validate every case; raises on any schema, reference or duplicate-id error."""
    raw = CorpusFile.model_validate_json(path.read_text(encoding="utf-8"))
    fixtures = {
        name: ScopeFixture.model_validate({"name": name, **body})
        for name, body in raw.scope_fixtures.items()
    }
    cases: list[InjectionCase] = []
    for entry in raw.cases:
        ref = entry.get("scope")
        if not isinstance(ref, str) or not _REF.match(ref) or ref not in fixtures:
            raise ValueError(f"case {entry.get('id')!r}: unknown scope fixture {ref!r}")
        cases.append(InjectionCase.model_validate({**entry, "scope": fixtures[ref]}))
    ids = [c.id for c in cases]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate case ids: {dupes}")
    return tuple(cases)
