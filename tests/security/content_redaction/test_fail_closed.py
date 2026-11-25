"""PRP-101 item 7: ``redact`` fails closed (acceptance criteria 1, 4 and 7).

Every failure path returns ``RedactionFailed(reason)`` and nothing else: no input text, no
partial output, no exception text, no log record. Covered here:

- a detector that raises with the secret in its message (``detector_error``);
- detectors returning malformed output (non-``Match`` objects, non-tuples, offsets past the
  end, ``start >= end``, negative offsets, unknown or undeclared categories, a foreign
  ``detector_id``, a bad confidence), including ``Match`` objects forged past
  ``Match.__post_init__``;
- every internal engine step monkeypatched to raise;
- the time budget, the size limit before and after NFKC expansion, and an unsafe overlap;
- a 200-seed property run mixing credentials, invisible characters, fullwidth forms, tight
  budgets and faulty detectors;
- a static scan of ``neurosphere_core/classification/**`` (see ``test_static_*``).
"""

from __future__ import annotations

import ast
import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest
from neurosphere_core.classification import (
    CustomerPattern,
    DetectorSet,
    Match,
    Redacted,
    RedactionBudget,
    RedactionConfig,
    RedactionFailed,
    RedactionResult,
    default_detector_set,
    engine,
    identifier_detectors,
    redact,
    secret_detectors,
)

from ._values import (
    ALL_PLACEHOLDERS,
    CREDENTIAL_GENERATORS,
    capture_all_loggers,
    leaked_fragments,
    log_text,
    secret_value,
)

CONFIG: Final = RedactionConfig()
PACKAGE: Final = Path(engine.__file__).resolve().parent


def _secret(seed: int = 0, kind: str = "github_pat_classic") -> tuple[str, str]:
    credential = CREDENTIAL_GENERATORS[kind](random.Random(f"fail:{kind}:{seed}"))
    return credential, secret_value(kind, credential)


CREDENTIAL, SECRET = _secret()
TEXT: Final = f"deploy with {CREDENTIAL} tonight"
SPAN: Final = (TEXT.index(SECRET), TEXT.index(SECRET) + len(SECRET))


def _forged(**fields: Any) -> Match:
    """A ``Match`` whose fields bypass ``__post_init__`` (a buggy or hostile detector)."""
    base: dict[str, Any] = {
        "start": SPAN[0],
        "end": SPAN[1],
        "category": "vendor_api_key",
        "confidence": "high",
        "detector_id": "fake",
        "sensitivity_category": None,
    }
    base.update(fields)
    match = object.__new__(Match)
    for name, value in base.items():
        object.__setattr__(match, name, value)
    return match


def _no_output(_text: str) -> tuple[()]:
    return ()


@dataclass
class Fake:
    """A Detector-protocol test double: fixed output on the first call, or a failure mode."""

    # default_factory, not a class-level lambda: CodeQL reads a class attribute lambda as a method.
    output: Callable[[str], object] = field(default_factory=lambda: _no_output)
    detector_id: str = "fake"
    version: str = "1.0.0"
    kinds: frozenset[str] = field(default_factory=lambda: frozenset({"vendor_api_key"}))
    always_redact: bool = True
    raise_on_call: int = 0  # 0 = never; n = raise on the n-th call
    error: BaseException | None = None
    sleep: float = 0.0
    calls: int = 0

    def find(self, text: str) -> tuple[Match, ...]:
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        if self.error is not None and self.calls == (self.raise_on_call or 1):
            raise self.error
        if self.calls > 1:
            return ()
        return cast("tuple[Match, ...]", self.output(text))


def _set(*fakes: Fake, defaults: bool = False) -> DetectorSet:
    base = secret_detectors() + identifier_detectors() if defaults else ()
    return DetectorSet(set_id="item7", version="item7-1.0.0", detectors=(*base, *fakes))


@pytest.fixture
def all_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    for _ in capture_all_loggers(caplog):
        yield caplog


def _surfaces(result: object) -> str:
    parts = [repr(result), str(result)]
    if isinstance(result, Redacted | RedactionFailed):
        parts.append(result.model_dump_json())
        parts.append(repr(result.model_dump()))
    return "\n".join(parts)


def _assert_failed(
    result: RedactionResult,
    reason: str,
    caplog: pytest.LogCaptureFixture,
    secret: str = SECRET,
) -> None:
    assert result == RedactionFailed(reason=cast("Any", reason)), repr(result)
    rendered = _surfaces(result) + "\n" + log_text(caplog.records)
    assert not leaked_fragments(secret, rendered, ()), "secret fragment in failure surfaces"
    assert not caplog.records, "classification must not log"


# --- RedactionFailed shape -------------------------------------------------------------------


def test_redaction_failed_carries_only_a_reason() -> None:
    assert set(RedactionFailed.model_fields) == {"reason"}
    assert RedactionFailed.model_config.get("extra") == "forbid"
    assert RedactionFailed.model_config.get("frozen") is True
    failed = RedactionFailed(reason="detector_error")
    assert failed.model_dump() == {"reason": "detector_error"}
    with pytest.raises(ValueError, match="Extra inputs"):
        RedactionFailed.model_validate({"reason": "detector_error", "text": "x"})


# --- raising detectors -----------------------------------------------------------------------


def _errors() -> list[BaseException]:
    noted = ValueError(f"cannot parse {SECRET}")
    noted.add_note(f"while scanning {SECRET}")
    chained = RuntimeError("wrapper")
    chained.__cause__ = KeyError(SECRET)
    return [
        ValueError(SECRET),
        noted,
        chained,
        TypeError(f"bad input {TEXT!r}"),
        RecursionError(SECRET),
        MemoryError(SECRET),
        UnicodeDecodeError("utf-8", SECRET.encode(), 0, 1, SECRET),
    ]


@pytest.mark.parametrize("error_index", range(len(_errors())))
@pytest.mark.parametrize("defaults", [False, True])
@pytest.mark.parametrize("call", [1, 2])
def test_detector_raising_with_secret_is_detector_error(
    all_logs: pytest.LogCaptureFixture, error_index: int, defaults: bool, call: int
) -> None:
    # call 1 = the detection pass, call 2 = the self-check pass over the output.
    fake = Fake(error=_errors()[error_index], raise_on_call=call)
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=_set(fake, defaults=defaults))
    if call == 2 and not defaults:
        # The fake reported nothing on call 1 and nothing else redacts: the self-check still
        # runs it (always_redact) and its exception must fail the part closed.
        assert fake.calls == 2
    _assert_failed(result, "detector_error", all_logs)


# --- malformed detector output ---------------------------------------------------------------


def _end() -> int:
    return len(TEXT)


MALFORMED: Final[dict[str, Callable[[str], object]]] = {
    "string_item": lambda _t: ("not a match",),
    "dict_item": lambda _t: ({"start": SPAN[0], "end": SPAN[1]},),
    "tuple_item": lambda _t: ((SPAN[0], SPAN[1], "vendor_api_key"),),
    "duck_item": lambda _t: (
        type("Duck", (), {"start": SPAN[0], "end": SPAN[1], "category": "vendor_api_key"})(),
    ),
    "list_not_tuple": lambda _t: [Match(*SPAN, "vendor_api_key", "high", "fake")],
    "none": lambda _t: None,
    "generator": lambda _t: (m for m in [Match(*SPAN, "vendor_api_key", "high", "fake")]),
    "end_past_text": lambda t: (Match(SPAN[0], len(t) + 1, "vendor_api_key", "high", "fake"),),
    "far_past_text": lambda t: (Match(0, len(t) * 4, "vendor_api_key", "high", "fake"),),
    "undeclared_category": lambda _t: (Match(*SPAN, "jwt", "high", "fake"),),
    "foreign_detector_id": lambda _t: (Match(*SPAN, "vendor_api_key", "high", "other"),),
    "forged_unknown_category": lambda _t: (_forged(category="not_a_category"),),
    "forged_bad_confidence": lambda _t: (_forged(confidence="certain"),),
    "forged_start_equals_end": lambda _t: (_forged(start=SPAN[0], end=SPAN[0]),),
    "forged_start_after_end": lambda _t: (_forged(start=SPAN[1], end=SPAN[0]),),
    "forged_negative_start": lambda _t: (_forged(start=-len(TEXT), end=SPAN[1]),),
    "forged_negative_both": lambda _t: (_forged(start=-len(TEXT), end=-1),),
    "forged_float_offsets": lambda _t: (_forged(start=float(SPAN[0]), end=float(SPAN[1])),),
    "forged_str_offsets": lambda _t: (_forged(start=str(SPAN[0]), end=str(SPAN[1])),),
    "forged_none_offsets": lambda _t: (_forged(start=None, end=None),),
}

#: Forged-``Match`` shapes (built with ``object.__new__``, bypassing ``Match.__post_init__``)
#: are included: ``engine._validated`` re-checks int offsets and ``0 <= start < end <= len``
#: itself, so every shape fails closed with or without the default detectors.


@pytest.mark.parametrize("defaults", [False, True])
@pytest.mark.parametrize("shape", sorted(MALFORMED))
def test_malformed_detector_output_fails_closed(
    all_logs: pytest.LogCaptureFixture, shape: str, defaults: bool
) -> None:
    fake = Fake(output=MALFORMED[shape])
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=_set(fake, defaults=defaults))
    assert isinstance(result, RedactionFailed), f"{shape}: not failed closed"
    _assert_failed(result, "detector_error", all_logs)


# --- internal steps raising ------------------------------------------------------------------

STEPS: Final = (
    "_normalize",
    "_Clock",
    "_detect",
    "_run_whole",
    "_validated",
    "_clusters",
    "_resolve",
    "_rewrite",
    "placeholder",
    "_findings",
    "Finding",
    "_self_check",
    "Redacted",
)


@pytest.mark.parametrize("step", STEPS)
def test_internal_step_raising_fails_closed(
    all_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    assert hasattr(engine, step), step

    def boom(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError(f"step failed on {TEXT}")

    monkeypatch.setattr(engine, step, boom)
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=default_detector_set())
    _assert_failed(result, "detector_error", all_logs)


def test_unicodedata_raising_fails_closed(
    all_logs: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_form: str, text: str) -> str:
        raise ValueError(text)

    # Patch the engine's module reference only: patching ``unicodedata`` itself breaks pytest.
    monkeypatch.setattr(engine, "unicodedata", SimpleNamespace(normalize=boom))
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=default_detector_set())
    _assert_failed(result, "detector_error", all_logs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": cast("Any", TEXT.encode())},
        {"config": cast("Any", {"default_mode": "keep"})},
        {"detector_set": cast("Any", secret_detectors())},
        {"budget": cast("Any", {"max_input_chars": 10})},
    ],
    ids=["bytes_text", "dict_config", "tuple_detectors", "dict_budget"],
)
def test_wrong_argument_types_fail_closed(
    all_logs: pytest.LogCaptureFixture, kwargs: dict[str, Any]
) -> None:
    call: dict[str, Any] = {
        "text": TEXT,
        "part": "prompt",
        "config": CONFIG,
        "detector_set": default_detector_set(),
    }
    call.update(kwargs)
    text = call.pop("text")
    result = redact(text, **call)
    _assert_failed(result, "detector_error", all_logs)


# --- budgets ---------------------------------------------------------------------------------


def test_slow_detector_is_budget_exhausted(all_logs: pytest.LogCaptureFixture) -> None:
    fake = Fake(sleep=0.05)
    budget = RedactionBudget(max_seconds=0.01)
    result = redact(
        TEXT, part="prompt", config=CONFIG, detector_set=_set(fake, defaults=True), budget=budget
    )
    _assert_failed(result, "budget_exhausted", all_logs)


def test_slow_customer_chunks_are_budget_exhausted(all_logs: pytest.LogCaptureFixture) -> None:
    dset = default_detector_set(
        patterns=(
            CustomerPattern(pattern_id="emp", pattern="EMP-[0-9]{6}", sensitivity_category="pii"),
        )
    )
    text = (TEXT + " EMP-123456 ") * 4000
    budget = RedactionBudget(max_seconds=0.001, chunk_chars=256, chunk_overlap=64)
    result = redact(text, part="prompt", config=CONFIG, detector_set=dset, budget=budget)
    _assert_failed(result, "budget_exhausted", all_logs)


def test_oversize_input_is_input_too_large(all_logs: pytest.LogCaptureFixture) -> None:
    budget = RedactionBudget(max_input_chars=len(TEXT) - 1)
    result = redact(
        TEXT, part="prompt", config=CONFIG, detector_set=default_detector_set(), budget=budget
    )
    _assert_failed(result, "input_too_large", all_logs)


def test_nfkc_expansion_over_limit_is_input_too_large(all_logs: pytest.LogCaptureFixture) -> None:
    # U+FDFA expands to 18 characters under NFKC: the raw input fits, the normalized one not.
    text = TEXT + " " + chr(0xFDFA) * 20
    budget = RedactionBudget(max_input_chars=len(text) + 10)
    assert len(text) <= budget.max_input_chars
    result = redact(
        text, part="prompt", config=CONFIG, detector_set=default_detector_set(), budget=budget
    )
    _assert_failed(result, "input_too_large", all_logs)


def test_unsafe_overlap_is_pattern_unsafe(all_logs: pytest.LogCaptureFixture) -> None:
    dset = default_detector_set(
        patterns=(
            CustomerPattern(
                pattern_id="wide", pattern="CASE-[0-9]{40}", sensitivity_category="other"
            ),
        )
    )
    budget = RedactionBudget(chunk_chars=256, chunk_overlap=16)
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=dset, budget=budget)
    _assert_failed(result, "pattern_unsafe", all_logs)


# --- property run ----------------------------------------------------------------------------

_INVISIBLES: Final = tuple(map(chr, (0x200B, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0xFE0F, 0xE0041)))
_PROPERTY_CONTEXTS: Final = (
    "Please use {} for the nightly job.",
    '{{"value": "{}"}}',
    "note: {}\n",
    "export NS_JOB_VALUE={}\n",
    "X-Request-Context: {}\r\n",
    "2026-11-24T10:00:00Z INFO detail={} status=ok",
)


def _fullwidth(value: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in value)


def _sprinkle(rng: random.Random, value: str) -> str:
    chars = list(value)
    for _ in range(rng.randint(1, 4)):
        chars.insert(rng.randrange(1, len(chars)), rng.choice(_INVISIBLES))
    return "".join(chars)


def _faulty(rng: random.Random) -> Fake:
    mode = rng.randrange(4)
    if mode == 0:
        return Fake(error=ValueError("x"), raise_on_call=rng.choice([1, 2]))
    if mode == 1:
        return Fake(output=MALFORMED[rng.choice(sorted(MALFORMED))])
    if mode == 2:
        return Fake(
            output=lambda t: (Match(0, max(1, len(t) // 2), "vendor_api_key", "low", "fake"),)
        )
    return Fake()


def test_property_redacted_or_failed_never_verbatim(all_logs: pytest.LogCaptureFixture) -> None:
    kinds = sorted(CREDENTIAL_GENERATORS)
    outcomes = {"redacted": 0, "failed": 0}
    problems: list[str] = []
    for seed in range(200):
        rng = random.Random(f"property:{seed}")
        kind = rng.choice(kinds)
        credential = CREDENTIAL_GENERATORS[kind](rng)
        secret = secret_value(kind, credential)
        template = rng.choice(_PROPERTY_CONTEXTS)
        shown = credential
        variant = rng.randrange(4)
        if variant == 1:
            shown = credential.replace(secret, _sprinkle(rng, secret))
        elif variant == 2 and "\n" not in secret:
            shown = credential.replace(secret, _fullwidth(secret))
        text = template.format(shown)
        detectors = (
            _set(_faulty(rng), defaults=True) if rng.random() < 0.3 else default_detector_set()
        )
        budget = RedactionBudget(
            max_input_chars=rng.choice([1_000_000, len(text), max(1, len(text) - 1)]),
            max_seconds=rng.choice([2.0, 2.0, 2.0, 1e-9]),
        )
        config = rng.choice(
            [CONFIG, RedactionConfig(default_mode="keep"), RedactionConfig(modes={"other": "keep"})]
        )
        all_logs.clear()
        result = redact(text, part="prompt", config=config, detector_set=detectors, budget=budget)
        label = f"seed {seed} kind {kind} variant {variant}"
        if all_logs.records:
            problems.append(f"{label}: log records")
        if isinstance(result, RedactionFailed):
            outcomes["failed"] += 1
            if leaked_fragments(secret, _surfaces(result), ()):
                problems.append(f"{label}: failure surface carries the secret")
            continue
        assert isinstance(result, Redacted), label
        outcomes["redacted"] += 1
        label_parts = tuple(p for p in credential.split(secret) if p)
        benign = (*template.split("{}"), *label_parts, *ALL_PLACEHOLDERS)
        if result.text == text:
            problems.append(f"{label}: input returned verbatim")
        if leaked_fragments(secret, _surfaces(result), benign):
            problems.append(f"{label}: secret window in output")
    assert not problems, problems
    assert outcomes["redacted"] > 50 and outcomes["failed"] > 20, outcomes


# --- static scan -----------------------------------------------------------------------------
#
# Pragmatic AST heuristic, not a proof: (1) no ``print`` call, no ``logging`` import or name,
# no ``warnings.warn``, no ``sys.stdout``/``sys.stderr`` use anywhere in the package; (2) no
# ``raise`` whose expression interpolates (f-string, ``%``, ``.format``, ``+``) or passes
# directly a variable whose name suggests content: text, value, match, term, pattern and
# their common spellings. Names are matched exactly or as ``_``-separated parts (``raw_text``,
# ``term_value``); attribute reads (``self.pattern``) count by their attribute name. ALL_CAPS
# names are module constants and exempt. Misses: content laundered through another variable
# name, or a raise of a pre-built message; the runtime tests above cover those paths.

_CONTENT_NAMES: Final = frozenset(
    {"text", "value", "match", "term", "pattern", "piece", "content", "raw", "found", "terms"}
)


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def _is_content(name: str) -> bool:
    if name.isupper():  # module constants (MAX_TERM_CHARS) are configuration, not content
        return False
    parts = set(name.lower().strip("_").split("_"))
    return bool(parts & _CONTENT_NAMES)


def _interpolations(node: ast.AST) -> list[ast.AST]:
    """Sub-expressions of a raise that build a string from variables."""
    found: list[ast.AST] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.FormattedValue):
            found.append(sub.value)
        elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod | ast.Add):
            found.append(sub)
        elif (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in {"format", "join", "format_map"}
        ):
            found.append(sub)
        elif isinstance(sub, ast.Call):
            found.extend(arg for arg in sub.args if isinstance(arg, ast.Name | ast.Attribute))
    return found


def _package_files() -> list[Path]:
    files = sorted(PACKAGE.rglob("*.py"))
    assert len(files) >= 9, files
    return files


def test_static_no_logging_print_or_stdio() -> None:
    offenders: list[str] = []
    for path in _package_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{path.name}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names]
                module = node.module if isinstance(node, ast.ImportFrom) else None
                if any(n.split(".")[0] in {"logging", "warnings"} for n in names) or (
                    module is not None and module.split(".")[0] in {"logging", "warnings"}
                ):
                    offenders.append(f"{where} imports logging/warnings")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"print", "breakpoint"}:
                    offenders.append(f"{where} calls {func.id}")
            elif isinstance(node, ast.Attribute):
                if node.attr in {"stdout", "stderr"} or (
                    isinstance(node.value, ast.Name) and node.value.id in {"logging", "logger"}
                ):
                    offenders.append(f"{where} touches {node.attr}")
            elif isinstance(node, ast.Name) and node.id in {"logger", "log", "LOGGER"}:
                offenders.append(f"{where} uses {node.id}")
    assert not offenders, offenders


def test_static_no_raise_interpolates_content() -> None:
    offenders: list[str] = []
    raises = 0
    for path in _package_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            raises += 1
            for expr in _interpolations(node.exc):
                bad = sorted(n for n in _names(expr) if _is_content(n))
                if bad:
                    offenders.append(f"{path.name}:{node.lineno} interpolates {bad}")
    assert raises >= 20, raises  # the scan actually saw the package's raise statements
    assert not offenders, offenders


def test_static_heuristic_catches_a_leaky_raise() -> None:
    """The scan above must flag the shapes it claims to flag."""
    leaky = [
        "raise ValueError(f'bad {text}')",
        "raise ValueError('bad %s' % raw_value)",
        "raise ValueError('bad {}'.format(match))",
        "raise ValueError('bad ' + self.pattern)",
        "raise ValueError(term)",
    ]
    safe = [
        "raise ValueError('unknown detected category')",
        "raise ValueError(f'term {index} must be 1..{limit} characters')",
        "raise _Fail('detector_error')",
    ]
    for source in leaky:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.Raise) and node.exc is not None
        assert any(_is_content(n) for e in _interpolations(node.exc) for n in _names(e)), source
    for source in safe:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.Raise) and node.exc is not None
        assert not any(_is_content(n) for e in _interpolations(node.exc) for n in _names(e)), source


def test_logging_module_untouched_by_redact(all_logs: pytest.LogCaptureFixture) -> None:
    """Runtime twin of the static scan: a full redact emits nothing at DEBUG on any logger."""
    result = redact(TEXT, part="prompt", config=CONFIG, detector_set=default_detector_set())
    assert isinstance(result, Redacted)
    assert not all_logs.records
    assert logging.getLogger().level == logging.DEBUG
