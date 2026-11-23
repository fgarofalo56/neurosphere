"""Recorded demo adapter (PRP-78 item 6): scripted questions, extractive answers, local only.

``NS_COPILOT_MODE=recorded`` composes this adapter, and only with ``NS_ENV=local`` (the builder
refuses it anywhere else; owner decision D15). It never reaches a model. For each of a fixed list
of demo questions (``fixtures/demo/*.json``) it:

1. emits the scripted tool call(s), with fixed JSON arguments;
2. once the real tool results are in the conversation, composes an EXTRACTIVE answer: every line
   quotes values from a record the tools actually returned and cites that record's ``cite_as``
   handle. The model (and so this adapter) sees handles, never record ids, so handles are read
   from the tool turns; none is ever invented or hard-coded.

Anything that matches no demo question gets a fixed answer without citations, which the engine
ends as an abstention. A ``timeline_meta`` record carries no citation and is never quoted.

Placeholders in script arguments (resolved when the call is emitted): ``"$now"`` and
``"$now-<n>d|h|m"`` become UTC timestamps from the adapter clock; ``"$id:<slug>"`` becomes the
``record_id`` of a record an earlier step returned whose id ends in ``:<slug>`` (canonical ids
carry the customer, so a fixed id could not match a seeded world).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from neurosphere_core.copilot.models.protocol import AdapterDescriptor
from neurosphere_core.copilot.models.types import (
    Completed,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallRequested,
)

__all__ = ["DEMO_DIR", "DemoScript", "RecordedDemoAdapter", "load_demo_scripts", "match_script"]

DEMO_DIR: Final = Path(__file__).parent / "fixtures" / "demo"

NOT_A_DEMO_QUESTION: Final = (
    "This is the recorded demo: it only answers a fixed list of demo questions, "
    "so it has nothing grounded to say about that."
)
_CONTEXT_MARKER: Final = "\n\nContext from the user's screen"
_META_KIND: Final = "timeline_meta"
_WORD: Final = re.compile(r"[a-z0-9]+")
_RELATIVE: Final = re.compile(r"^\$now(?:-(\d{1,4})([dhm]))?$")
_UNITS: Final = {"d": "days", "h": "hours", "m": "minutes"}


class DemoStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    arguments: dict[str, Any]


class DemoAnswer(BaseModel):
    """How the extractive answer is laid out. Values always come from tool records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intro: str
    empty: str
    exclude_kinds: tuple[str, ...] = ()
    label_fields: tuple[str, ...]
    detail_fields: tuple[str, ...] = ()
    show_kind: bool = False
    max_items: int = Field(default=10, ge=1, le=50)


class DemoScript(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    # Any group whose words are all present in the question matches it.
    phrases: tuple[tuple[str, ...], ...] = Field(min_length=1)
    steps: tuple[DemoStep, ...] = Field(min_length=1)
    answer: DemoAnswer


def _words(text: str) -> set[str]:
    found = _WORD.findall(text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in found}


@lru_cache(maxsize=1)
def load_demo_scripts() -> tuple[DemoScript, ...]:
    return tuple(
        DemoScript.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(DEMO_DIR.glob("*.json"))
    )


def match_script(question: str) -> DemoScript | None:
    """The script whose best phrase group is fully present (largest group wins), else ``None``."""
    present = _words(question)
    best: tuple[int, DemoScript] | None = None
    for script in load_demo_scripts():
        for group in script.phrases:
            if _words(" ".join(group)) <= present and (best is None or len(group) > best[0]):
                best = (len(group), script)
    return None if best is None else best[1]


def _question(content: str) -> str:
    return content.split(_CONTEXT_MARKER, 1)[0].strip()


class _UnresolvedError(Exception):
    """A ``$id:`` placeholder matched no record an earlier step returned."""


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve(value: Any, now: datetime, seen: Sequence[Mapping[str, Any]]) -> Any:
    if isinstance(value, dict):
        return {k: _resolve(v, now, seen) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_resolve(v, now, seen) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(value, str):
        return value
    relative = _RELATIVE.match(value)
    if relative is not None:
        amount, unit = relative.groups()
        delta = timedelta(**{_UNITS[unit]: int(amount)}) if amount else timedelta(0)
        return _timestamp(now - delta)
    if value.startswith("$id:"):
        slug = value[4:]
        for payload in seen:
            for record in _records(payload):
                record_id = str(record.get("record_id", ""))
                if record_id.rsplit(":", 1)[-1] == slug:
                    return record_id
        raise _UnresolvedError(slug)
    return value


def _payload(content: str) -> Mapping[str, Any]:
    try:
        parsed: Any = json.loads(content)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw: Any = payload.get("records")
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]  # pyright: ignore[reportUnknownVariableType]


def _lookup(data: Mapping[str, Any], path: str) -> list[str]:
    """Scalar value(s) at ``path``; a list of objects contributes one value per distinct item."""
    head, _, rest = path.partition(".")
    value: Any = data.get(head)
    items: list[Any] = value if isinstance(value, list) else [value]  # pyright: ignore[reportUnknownVariableType]
    out: list[str] = []
    for item in items:
        if rest and isinstance(item, dict):
            item = item.get(rest)  # pyright: ignore[reportUnknownVariableType]
        if isinstance(item, (str, int, float, bool)) and str(item) not in out:
            out.append(str(item))
    return out


def _line(answer: DemoAnswer, record: Mapping[str, Any]) -> str:
    data: Any = record.get("data")
    fields: Mapping[str, Any] = data if isinstance(data, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    label = next(
        (found[0] for name in answer.label_fields if (found := _lookup(fields, name))),
        str(record.get("record_id", "record")),
    )
    if answer.show_kind:
        label = f"{record.get('kind', 'record')}: {label}"
    details = [
        f"{name.rsplit('.', 1)[-1]} {', '.join(found)}"
        for name in answer.detail_fields
        if (found := _lookup(fields, name))
    ]
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"- {label}{suffix} [cite:{record['cite_as']}]"


def compose_answer(script: DemoScript, payload: Mapping[str, Any]) -> str:
    """The extractive answer: only returned records, only their own ``cite_as`` handles."""
    answer = script.answer
    usable = [
        r
        for r in _records(payload)
        if isinstance(r.get("cite_as"), str)
        and r.get("kind") != _META_KIND
        and r.get("record_id") != _META_KIND
        and r.get("kind") not in answer.exclude_kinds
    ]
    if not usable:
        return answer.empty
    shown = usable[: answer.max_items]
    lines = [answer.intro, *(_line(answer, r) for r in shown)]
    if len(usable) > len(shown) or payload.get("truncated") is True:
        lines.append("More rows exist than are shown here.")
    return "\n".join(lines)


class RecordedDemoAdapter:
    """Scripted demo conversations over the real tools; never contacts a model."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._descriptor = AdapterDescriptor(kind="fixture", name="recorded-demo", synthetic=True)

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        turns = request.turns
        last_user = max((i for i, t in enumerate(turns) if t.role == "user"), default=-1)
        question = _question(turns[last_user].content) if last_user >= 0 else ""
        script = match_script(question)
        if script is None:
            yield TextDelta(text=NOT_A_DEMO_QUESTION)
            yield Completed(stop_reason="end_turn")
            return
        payloads = [_payload(t.content) for t in turns[last_user + 1 :] if t.role == "tool"]
        done = len(payloads)
        if done < len(script.steps):
            step = script.steps[done]
            try:
                arguments = _resolve(step.arguments, self._clock(), payloads)
            except _UnresolvedError:
                yield TextDelta(text=script.answer.empty)
                yield Completed(stop_reason="end_turn")
                return
            yield ToolCallRequested(
                call_id=f"demo-{script.id}-{done + 1}"[:128],
                tool_name=step.tool,
                arguments=arguments,
            )
            yield Completed(stop_reason="tool_calls")
            return
        yield TextDelta(text=compose_answer(script, payloads[-1]))
        yield Completed(stop_reason="end_turn")
