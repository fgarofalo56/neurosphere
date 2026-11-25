# ruff: noqa: S311 - seeded, reproducible synthetic data, not cryptography
"""PRP-101 item 5: the fail-closed redaction engine (criteria 1, 4, 5 and 6).

No credential-shaped literal lives here: credentials come from ``synth`` generators and card
numbers are built at runtime with a Luhn check digit.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from neurosphere_contracts.interactions.v1.detection_finding import DetectionFinding
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.classification import (
    CREDENTIAL_CATEGORIES,
    PLACEHOLDER_RE,
    Category,
    CustomerDictionary,
    CustomerPattern,
    DetectorSet,
    Finding,
    Match,
    Redacted,
    RedactionBudget,
    RedactionConfig,
    RedactionFailed,
    RedactionResult,
    default_detector_set,
    engine,
    placeholder,
    redact,
)
from neurosphere_core.classification.detectors.secret_detectors import secret_detectors

from .synth import CREDENTIAL_GENERATORS, EXPECTED_CATEGORY, secret_value

_CONTRACT_TESTS = Path(__file__).resolve().parents[4] / "tests" / "contracts"
_SPEC = importlib.util.spec_from_file_location(
    "ns_contract_validators_prp101_item5", _CONTRACT_TESTS / "validators.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_VALIDATORS = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _VALIDATORS
sys.path.insert(0, str(_CONTRACT_TESTS))  # validators imports its sibling contract_support
try:
    _SPEC.loader.exec_module(_VALIDATORS)
    _SUPPORT = importlib.import_module("contract_support")
finally:
    sys.path.remove(str(_CONTRACT_TESTS))
check_secret_free_text = _VALIDATORS.check_secret_free_text

_REDACTED_SCHEMA = "interactions/v1/redacted-content.schema.json"
_FINDING_SCHEMA = "interactions/v1/detection-finding.schema.json"

DEFAULT = default_detector_set()
CONFIG = RedactionConfig()
SEEDS = range(4)
CONTEXTS = (
    "Please use {} for the nightly job and report back.",
    '{{"value": "{}", "n": 1}}',
    "settings:\n  note: {}\n  retries: 3\n",
    "settings:\n  token: {}\n  retries: 3\n",
)


def _run(text: str, **kwargs: Any) -> RedactionResult:
    kwargs.setdefault("part", "prompt")
    kwargs.setdefault("config", CONFIG)
    kwargs.setdefault("detector_set", DEFAULT)
    return redact(text, **kwargs)


def _ok(text: str, **kwargs: Any) -> Redacted:
    result = _run(text, **kwargs)
    assert isinstance(result, Redacted), result
    return result


def _card(rng: random.Random) -> str:
    """A Luhn-valid 16-digit number built at runtime."""
    body = [4] + [rng.randrange(10) for _ in range(14)]
    total = 0
    for i, digit in enumerate(reversed(body)):
        doubled = digit * 2 if i % 2 == 0 else digit
        total += doubled - 9 if doubled > 9 else doubled
    return "".join(map(str, body)) + str((10 - total % 10) % 10)


def _email(rng: random.Random) -> str:
    return f"user{rng.randrange(1000)}@example.org"


@dataclass
class _Fake:
    """A test detector with fixed spans (or a failure mode)."""

    detector_id: str
    category: Category
    spans: tuple[tuple[int, int], ...] = ()
    always_redact: bool = False
    version: str = "1.0.0"
    confidence: str = "high"
    sleep: float = 0.0
    error: str | None = None
    #: Spans are reported on the first call only (the input), not on the engine's self-check
    #: pass over the output, so fixed offsets do not "find" text that was already replaced.
    calls: int = 0
    kinds: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self.kinds = frozenset({self.category})

    def find(self, text: str) -> tuple[Match, ...]:
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        if self.error is not None:
            raise ValueError(self.error + text)
        if self.calls > 1:
            return ()
        return tuple(
            Match(
                start=s,
                end=e,
                category=self.category,
                confidence=cast("Any", self.confidence),
                detector_id=self.detector_id,
            )
            for s, e in self.spans
            if e <= len(text)
        )


def _fake_set(*fakes: _Fake) -> DetectorSet:
    return DetectorSet(set_id="test", version="test-1", detectors=fakes)


def _assert_no_text(result: object, text: str) -> None:
    for rendered in (repr(result), str(result)):
        assert text not in rendered
    if isinstance(result, RedactionFailed):
        assert set(type(result).model_fields) == {"reason"}


# --- criterion 4: fail closed -----------------------------------------------------------------


def test_detector_exception_fails_closed_without_text() -> None:
    secret = "".join(["hunter", "-", "two", "-", "x" * 8])
    text = f"my value is {secret} ok"
    bad = _Fake("boom", "other", error=f"leak {secret} ")
    result = _run(text, detector_set=_fake_set(bad))
    assert result == RedactionFailed(reason="detector_error")
    _assert_no_text(result, secret)


def test_exception_during_findings_construction_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(1)
    text = f"card {_card(rng)} and mail {_email(rng)}"

    def explode(**kwargs: object) -> Finding:
        raise RuntimeError(f"bad finding {text}")

    monkeypatch.setattr(engine, "Finding", explode)
    result = _run(text)
    assert result == RedactionFailed(reason="detector_error")
    _assert_no_text(result, text)


def test_exception_in_rewrite_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object) -> object:
        raise KeyError("x")

    monkeypatch.setattr(engine, "_rewrite", explode)
    assert _run("mail a@example.org") == RedactionFailed(reason="detector_error")


@pytest.mark.parametrize(
    "fake",
    [
        _Fake("wrong-id", "other", spans=((0, 2),)),
        _Fake("past-end", "other", spans=((0, 2),)),
    ],
)
def test_malformed_detector_output_fails_closed(fake: _Fake) -> None:
    class Wrong(_Fake):
        def find(self, text: str) -> tuple[Match, ...]:
            if self.detector_id == "wrong-id":
                return (Match(0, 2, "other", "high", "someone-else"),)
            return (Match(0, len(text) + 5, "other", "high", self.detector_id),)

    wrong = Wrong(fake.detector_id, fake.category)
    assert _run("abcdef", detector_set=_fake_set(wrong)) == RedactionFailed(reason="detector_error")


def test_detector_returning_undeclared_category_fails_closed() -> None:
    class Liar(_Fake):
        def find(self, text: str) -> tuple[Match, ...]:
            return (Match(0, 2, "jwt", "high", self.detector_id),)

    assert _run("abcdef", detector_set=_fake_set(Liar("liar", "other"))) == RedactionFailed(
        reason="detector_error"
    )


def test_non_str_input_fails_closed() -> None:
    assert _run(cast("str", b"bytes")) == RedactionFailed(reason="detector_error")


def test_keyboard_interrupt_is_not_swallowed() -> None:
    class Interrupt(_Fake):
        def find(self, text: str) -> tuple[Match, ...]:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run("abc", detector_set=_fake_set(Interrupt("int", "other")))


def test_slow_detector_exhausts_budget() -> None:
    slow = _Fake("slow", "other", sleep=0.05)
    other = _Fake("other", "other")
    budget = RedactionBudget(max_seconds=0.01)
    result = _run("some text", detector_set=_fake_set(slow, other), budget=budget)
    assert result == RedactionFailed(reason="budget_exhausted")


def test_slow_customer_chunks_exhaust_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = CustomerPattern(pattern_id="emp", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    dset = DetectorSet(set_id="t", version="t-1", detectors=(), patterns=(pattern,))
    detector = dset.customer_detectors[0]
    real_find = type(detector).find

    def slow_find(self: object, text: str) -> tuple[Match, ...]:
        time.sleep(0.02)
        return real_find(cast("Any", self), text)

    monkeypatch.setattr(type(detector), "find", slow_find)
    budget = RedactionBudget(max_seconds=0.05, chunk_chars=100, chunk_overlap=30)
    assert _run("x " * 2000, detector_set=dset, budget=budget) == RedactionFailed(
        reason="budget_exhausted"
    )


def test_oversize_input_fails_closed() -> None:
    budget = RedactionBudget(max_input_chars=10)
    assert _run("x" * 11, budget=budget) == RedactionFailed(reason="input_too_large")
    assert isinstance(_run("x" * 10, budget=budget), Redacted)


def test_nfkc_expansion_is_size_checked_again() -> None:
    expanding = "\ufdfa"  # one character, NFKC expands to 18
    budget = RedactionBudget(max_input_chars=10)
    assert _run(expanding, budget=budget) == RedactionFailed(reason="input_too_large")


def test_customer_width_above_overlap_is_pattern_unsafe() -> None:
    term = "Project " + "w" * 248  # 256 characters: 2 * 256 + 2 > 512
    dictionary = CustomerDictionary(dictionary_id="d", terms=(term,), sensitivity_category="cui")
    dset = default_detector_set(dictionaries=(dictionary,))
    assert _run("hello", detector_set=dset) == RedactionFailed(reason="pattern_unsafe")
    wide = RedactionBudget(chunk_chars=4096, chunk_overlap=1024)
    assert isinstance(_run("hello", detector_set=dset, budget=wide), Redacted)


def test_pattern_width_rule_uses_two_widths_plus_two() -> None:
    pattern = CustomerPattern(pattern_id="p", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    dset = DetectorSet(set_id="t", version="t-1", detectors=(), patterns=(pattern,))
    assert dset.customer_max_width == 10
    tight = RedactionBudget(chunk_chars=100, chunk_overlap=21)
    exact = RedactionBudget(chunk_chars=100, chunk_overlap=22)
    assert _run("x", detector_set=dset, budget=tight) == RedactionFailed(reason="pattern_unsafe")
    assert isinstance(_run("x", detector_set=dset, budget=exact), Redacted)


# --- criterion 5: findings and modes ---------------------------------------------------------


def _check_offsets(result: Redacted) -> None:
    for finding in result.findings:
        for start, end in finding.offsets:
            if finding.action == "replaced":
                assert result.text[start:end] == placeholder(finding.category)


def test_finding_fields_are_exactly_the_contract_fields() -> None:
    assert set(Finding.model_fields) == {
        "category",
        "part",
        "detector_id",
        "detector_version",
        "count",
        "action",
        "confidence",
        "offsets",
        "sensitivity_category",
    }


@pytest.mark.parametrize("kind", ["jwt", "aws_access_key_id", "password_assignment"])
def test_credentials_replaced_even_with_default_keep(kind: str) -> None:
    cred = CREDENTIAL_GENERATORS[kind](random.Random(3))
    result = _ok(f"use {cred} now", config=RedactionConfig(default_mode="keep"))
    finding = next(f for f in result.findings if f.category == EXPECTED_CATEGORY[kind])
    assert finding.action == "replaced"
    assert finding.sensitivity_category == "credentials"
    assert secret_value(kind, cred) not in result.text
    _check_offsets(result)


def test_opaque_secret_replaced_even_when_other_is_kept() -> None:
    cred = CREDENTIAL_GENERATORS["opaque_secret"](random.Random(5))
    config = RedactionConfig(default_mode="keep", modes={"other": "keep"})
    result = _ok(f"blob {cred} end", config=config)
    assert result.text == f"blob {placeholder('other')} end"
    (finding,) = result.findings
    assert (finding.category, finding.detector_id, finding.action) == (
        "other",
        "opaque_secret",
        "replaced",
    )


def test_email_kept_when_configured() -> None:
    email = _email(random.Random(1))
    text = f"write to {email} please"
    result = _ok(text, config=RedactionConfig(modes={"email_address": "keep"}))
    assert result.text == text
    (finding,) = result.findings
    assert (finding.category, finding.action, finding.count) == ("email_address", "kept", 1)
    ((start, end),) = finding.offsets
    assert result.text[start:end] == email
    assert finding.sensitivity_category == "pii"


def test_card_replaced_by_default_and_kept_when_configured() -> None:
    card = _card(random.Random(7))
    text = f"card {card} on file"
    result = _ok(text)
    assert result.text == f"card {placeholder('payment_card')} on file"
    (finding,) = result.findings
    assert (finding.action, finding.sensitivity_category) == ("replaced", "pci")
    _check_offsets(result)
    kept = _ok(text, config=RedactionConfig(modes={"payment_card": "keep"}))
    assert kept.text == text
    assert [f.action for f in kept.findings] == ["kept"]


def test_findings_count_offsets_and_order() -> None:
    rng = random.Random(11)
    cards = [_card(rng) for _ in range(3)]
    email = _email(rng)
    text = f"a {cards[0]} b {email} c {cards[1]} d {cards[2]}"
    result = _ok(text)
    _check_offsets(result)
    assert [f.category for f in result.findings] == ["payment_card", "email_address"]
    card_finding = result.findings[0]
    assert card_finding.count == 3
    assert len(card_finding.offsets) == 3
    starts = [s for f in result.findings for s, _ in f.offsets[:1]]
    assert starts == sorted(starts)


def test_offsets_capped_at_64_count_exact() -> None:
    rng = random.Random(2)
    text = " ".join(f"x {_card(rng)}" for _ in range(70))
    result = _ok(text)
    (finding,) = result.findings
    assert finding.count == 70
    assert len(finding.offsets) == 64
    _check_offsets(result)


def test_finding_dump_validates_as_detection_finding() -> None:
    rng = random.Random(4)
    cred = CREDENTIAL_GENERATORS["jwt"](rng)
    config = RedactionConfig(modes={"email_address": "keep"})
    result = _ok(f"t {cred} m {_email(rng)} c {_card(rng)}", config=config)
    assert {f.action for f in result.findings} == {"replaced", "kept"}
    for finding in result.findings:
        doc = _finding_doc(finding)
        assert not _SUPPORT.schema_errors(_FINDING_SCHEMA, doc)
        DetectionFinding.model_validate(doc)


def _finding_doc(finding: Finding) -> dict[str, Any]:
    doc = finding.model_dump(mode="json")
    doc.pop("sensitivity_category")
    doc["spans"] = [{"start": s, "end": e} for s, e in doc.pop("offsets")]
    return doc


# --- criteria 1 and 6: every generator kind, several contexts --------------------------------


def _redacted_content(result: Redacted) -> dict[str, Any]:
    return {
        "schema_version": "1.2.0",
        "interaction_id": "7c1f2c9e-3b1a-4c55-9f0a-5d2e8a1b6c40",
        "redaction_state": "redacted" if result.findings else "not_required",
        "detector_set_version": result.set_version,
        "parts": [
            {
                "part": "prompt",
                "text": result.text,
                "truncated": False,
                "findings": [_finding_doc(f) for f in result.findings],
            }
        ],
    }


def _fragments(secret: str, size: int = 6) -> set[str]:
    return {secret[i : i + size] for i in range(len(secret) - size + 1)}


@pytest.mark.parametrize("kind", sorted(CREDENTIAL_GENERATORS))
def test_every_kind_redacts_to_secret_free_schema_valid_content(kind: str) -> None:
    for seed in SEEDS:
        cred = CREDENTIAL_GENERATORS[kind](random.Random(seed))
        secret = secret_value(kind, cred)
        for context in CONTEXTS:
            text = context.format(cred)
            result = _ok(text, config=RedactionConfig(default_mode="keep"))
            assert check_secret_free_text(result.text) == [], (kind, seed)
            doc = _redacted_content(result)
            assert not _SUPPORT.schema_errors(_REDACTED_SCHEMA, doc), (kind, seed)
            RedactedContent.model_validate(doc)
            # Replaced as a credential: overlapping credential detectors may name the
            # placeholder (an ``api-key:`` header also reads as a password assignment); the
            # longest credential span wins, so the category is one of the credential ones.
            assert result.findings, (kind, seed)
            assert all(f.action == "replaced" for f in result.findings), (kind, seed)
            assert all(
                f.category in CREDENTIAL_CATEGORIES or f.category == EXPECTED_CATEGORY[kind]
                for f in result.findings
            ), (kind, seed)
            # Criterion 1: no 6-character fragment of the secret survives, and nothing but
            # the typed placeholder stands where it was (no hash, length or partial value).
            residue = PLACEHOLDER_RE.sub("", result.text)
            leaked = {f for f in _fragments(secret) if f in residue and f not in context}
            assert not leaked, (kind, seed)
            if secret == cred and kind != "private_key_block_truncated":  # spans to text end
                assert PLACEHOLDER_RE.sub("", result.text) == context.format(""), (kind, seed)
            _check_offsets(result)


# --- normalization (Clarification 7) ---------------------------------------------------------


def test_full_width_card_is_detected() -> None:
    card = _card(random.Random(9))
    full_width = "".join(chr(0xFF10 + int(d)) for d in card)
    result = _ok(f"card {full_width} ok")
    assert result.text == f"card {placeholder('payment_card')} ok"


@pytest.mark.parametrize("kind", ["jwt", "aws_access_key_id"])
def test_zero_width_inside_credential_is_detected(kind: str) -> None:
    cred = CREDENTIAL_GENERATORS[kind](random.Random(6))
    middle = len(cred) // 2
    for joiner in ("\u200b", "\u200d", "\ufeff", "\u00ad", "\u202e"):
        evasive = cred[:middle] + joiner + cred[middle:]
        result = _ok(f"x {evasive} y")
        assert result.text == f"x {placeholder(cast('Any', EXPECTED_CATEGORY[kind]))} y"


#: One representative per Default_Ignorable_Code_Point block (review of item 5): each must be
#: stripped so it cannot split a credential past the detectors.
_IGNORABLE_SAMPLES = tuple(
    chr(cp)
    for cp in (
        0x115F, 0x1160, 0x17B4, 0x180B, 0x2065, 0x2800, 0x3164, 0xFE0F,
        0xFFA0, 0xFFF0, 0x1BCA0, 0x1D173, 0xE0020, 0xE0100,
    )
)  # fmt: skip


@pytest.mark.parametrize(
    "kind", ["aws_access_key_id", "apim_subscription_key_header", "opaque_secret", "jwt"]
)
@pytest.mark.parametrize("ignorable", _IGNORABLE_SAMPLES, ids=lambda c: f"U+{ord(c):04X}")
def test_default_ignorable_inside_credential_is_detected(kind: str, ignorable: str) -> None:
    cred = CREDENTIAL_GENERATORS[kind](random.Random(8))
    middle = len(cred) // 2
    result = _ok(f"key {cred[:middle]}{ignorable}{cred[middle:]} end")
    assert ignorable not in result.text
    secret = secret_value(kind, cred)
    for start in range(len(secret) - 5):
        assert secret[start : start + 6] not in result.text


def test_output_is_normalized_text() -> None:
    result = _ok("\uff46\uff55\uff4c\uff4c\u200bwidth")
    assert result.text == "fullwidth"
    assert result.findings == ()


# --- idempotence, determinism, overlap -------------------------------------------------------


def _mixed_text(rng: random.Random) -> str:
    parts = [f"{kind}: {gen(rng)}" for kind, gen in sorted(CREDENTIAL_GENERATORS.items())]
    parts += [f"card {_card(rng)}", f"mail {_email(rng)}", "plain words here"]
    return "\n".join(parts)


def test_idempotent() -> None:
    for seed in SEEDS:
        first = _ok(_mixed_text(random.Random(seed)))
        second = _ok(first.text)
        assert second.text == first.text
        assert second.findings == ()


def test_idempotent_with_kept_categories() -> None:
    config = RedactionConfig(modes={"email_address": "keep"})
    first = _ok(_mixed_text(random.Random(1)), config=config)
    second = _ok(first.text, config=config)
    assert second.text == first.text
    assert all(f.action == "kept" for f in second.findings)
    assert second.findings == tuple(f for f in first.findings if f.action == "kept")


def test_deterministic() -> None:
    text = _mixed_text(random.Random(8))
    results = {_ok(text).model_dump_json() for _ in range(3)}
    assert len(results) == 1


def test_connection_string_with_key_and_url_is_one_placeholder() -> None:
    cred = CREDENTIAL_GENERATORS["service_bus_connection_string"](random.Random(2))
    assert "://" in cred
    result = _ok(f"conn: {cred}")
    assert result.text == f"conn: {placeholder('connection_string')}"
    (finding,) = result.findings
    assert (finding.category, finding.count) == ("connection_string", 1)


def test_partially_overlapping_credentials_get_one_placeholder_over_union() -> None:
    a = _Fake("cred-a", "jwt", spans=((2, 8),))
    b = _Fake("cred-b", "bearer_token", spans=((5, 12),))
    result = _ok("..abcdefghijkl..", detector_set=_fake_set(a, b))
    # b is longer, so its category names the placeholder over the union 2..12.
    assert result.text == f"..{placeholder('bearer_token')}kl.."
    (finding,) = result.findings
    assert (finding.detector_id, finding.count) == ("cred-b", 1)


def test_kept_category_overlapping_credential_is_covered() -> None:
    cred = _Fake("cred", "password_assignment", spans=((4, 10),))
    mail = _Fake("mail", "email_address", spans=((7, 16),))
    config = RedactionConfig(modes={"email_address": "keep"})
    result = _ok("abc 0123456789abcdef", config=config, detector_set=_fake_set(cred, mail))
    assert result.text == f"abc {placeholder('password_assignment')}cdef"
    assert [f.detector_id for f in result.findings] == ["cred"]


def test_credential_beats_longer_always_redact_other() -> None:
    cred = _Fake("cred", "jwt", spans=((0, 6),))
    opaque = _Fake("opaque", "other", spans=((0, 10),), always_redact=True)
    result = _ok("0123456789 tail", detector_set=_fake_set(opaque, cred))
    assert result.text == f"{placeholder('jwt')} tail"


def test_transitive_cluster_replaced_whole() -> None:
    a = _Fake("a", "email_address", spans=((0, 4),))
    b = _Fake("b", "phone_number", spans=((3, 8),))
    c = _Fake("c", "jwt", spans=((7, 10),))
    result = _ok("0123456789xyz", detector_set=_fake_set(a, b, c))
    assert result.text == f"{placeholder('jwt')}xyz"


def test_all_kept_cluster_keeps_text_and_reports_top_member() -> None:
    a = _Fake("a", "email_address", spans=((0, 4),))
    b = _Fake("b", "phone_number", spans=((2, 9),))
    result = _ok(
        "0123456789", config=RedactionConfig(default_mode="keep"), detector_set=_fake_set(a, b)
    )
    assert result.text == "0123456789"
    (finding,) = result.findings
    assert (finding.detector_id, finding.action, finding.offsets) == ("b", "kept", ((2, 9),))


# --- chunking of customer detectors ---------------------------------------------------------


_SMALL_CHUNKS = RedactionBudget(chunk_chars=64, chunk_overlap=40)


def test_customer_pattern_straddling_chunk_boundaries_found_once() -> None:
    pattern = CustomerPattern(pattern_id="emp", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    dset = DetectorSet(set_id="t", version="t-1", detectors=(), patterns=(pattern,))
    ident = "EMP-" + "".join(str(i % 10) for i in range(3, 9))
    for offset in range(0, 140):
        text = "z" * offset + ident + " tail " + "z" * 30
        result = _ok(text, detector_set=dset, budget=_SMALL_CHUNKS)
        assert result.text.count(placeholder("customer_identifier_pattern")) == 1, offset
        (finding,) = result.findings
        assert finding.count == 1
        assert finding.offsets == (
            (offset, offset + len(placeholder("customer_identifier_pattern"))),
        )


def test_dictionary_term_straddling_chunk_boundaries_found_once() -> None:
    dictionary = CustomerDictionary(
        dictionary_id="code-names", terms=("Project Falcon",), sensitivity_category="cui"
    )
    dset = DetectorSet(set_id="t", version="t-1", detectors=(), dictionaries=(dictionary,))
    token = placeholder("customer_dictionary_term")
    for offset in range(0, 140):
        text = "y" * offset + " project falcon " + "y" * 30
        result = _ok(text, detector_set=dset, budget=_SMALL_CHUNKS)
        assert result.text.count(token) == 1, offset
        (finding,) = result.findings
        assert (finding.count, finding.sensitivity_category) == (1, "cui")
        # A longer word is never matched, at any chunk edge.
        longer = "y" * offset + " project falconry " + "y" * 30
        assert _ok(longer, detector_set=dset, budget=_SMALL_CHUNKS).findings == (), offset


# --- detector set ----------------------------------------------------------------------------


def test_default_set_shape() -> None:
    ids = [d.detector_id for d in DEFAULT.all_detectors]
    assert len(ids) == len(set(ids)) == 17
    assert DEFAULT.version == "ns-detectors-1.0.0"
    assert len(DEFAULT.digest) == 64
    assert _ok("x").set_version == DEFAULT.version


def test_digest_tracks_configuration() -> None:
    d1 = CustomerDictionary(dictionary_id="d", terms=("Alpha",), sensitivity_category="cui")
    d2 = CustomerDictionary(dictionary_id="d", terms=("Bravo",), sensitivity_category="cui")
    p1 = CustomerPattern(pattern_id="p", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    p2 = CustomerPattern(pattern_id="p", pattern="EMP-[0-9]{7}", sensitivity_category="pii")
    digests = {
        default_detector_set().digest,
        default_detector_set(dictionaries=(d1,)).digest,
        default_detector_set(dictionaries=(d2,)).digest,
        default_detector_set(patterns=(p1,)).digest,
        default_detector_set(patterns=(p2,)).digest,
    }
    assert len(digests) == 5
    assert default_detector_set(dictionaries=(d1,)).digest == (
        default_detector_set(dictionaries=(d1,)).digest
    )
    v1 = _fake_set(_Fake("f", "other", version="1.0.0")).digest
    v2 = _fake_set(_Fake("f", "other", version="1.0.1")).digest
    assert v1 != v2
    assert "Alpha" not in repr(default_detector_set(dictionaries=(d1,)))


def test_detector_set_refuses_bad_members() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _fake_set(_Fake("f", "other"), _Fake("f", "jwt"))
    with pytest.raises(TypeError):
        DetectorSet(set_id="t", version="t-1", detectors=(cast("Any", object()),))
    customer = default_detector_set(
        patterns=(
            CustomerPattern(pattern_id="p", pattern="EMP-[0-9]{6}", sensitivity_category="pii"),
        )
    ).customer_detectors
    with pytest.raises(TypeError):
        DetectorSet(set_id="t", version="t-1", detectors=customer)
    with pytest.raises(ValueError):
        DetectorSet(set_id="t", version="Bad Version", detectors=())
    with pytest.raises(ValueError):
        _fake_set(_Fake("f", "other", version="v1"))


def test_self_check_catches_credential_left_in_output() -> None:
    # A fake that "finds" a credential only in a placeholder-free region the engine keeps
    # cannot happen with honest detectors; simulate one that matches on the second pass.
    class SecondPass(_Fake):
        calls = 0

        def find(self, text: str) -> tuple[Match, ...]:
            SecondPass.calls += 1
            if SecondPass.calls == 1:
                return ()
            return (Match(0, 1, "jwt", "high", self.detector_id),)

    result = _run("abc", detector_set=_fake_set(SecondPass("sp", "jwt", always_redact=True)))
    assert result == RedactionFailed(reason="detector_error")


# --- purity ----------------------------------------------------------------------------------


_PACKAGE = Path(engine.__file__).resolve().parent


def test_classification_imports_no_contracts_services_or_logging() -> None:
    files = list(_PACKAGE.rglob("*.py"))
    assert len(files) >= 7
    forbidden = {"neurosphere_contracts", "neurosphere_api", "neurosphere_workers", "logging"}
    offenders: dict[str, list[str]] = {}
    for path in files:
        roots: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        if roots & forbidden:
            offenders[path.name] = sorted(roots & forbidden)
    assert not offenders, offenders


# --- performance smoke -----------------------------------------------------------------------


def test_256_kib_mixed_text_within_default_budget() -> None:
    rng = random.Random(42)
    prose = "The quarterly review covers spend, latency and adoption across teams. "
    blocks: list[str] = []
    while sum(map(len, blocks)) < 256 * 1024:
        blocks.append(prose * 3)
        blocks.append(
            f"Contact {_email(rng)} or card {_card(rng)}; ticket EMP-{rng.randrange(10**6):06d}."
        )
        if rng.random() < 0.2:
            kind = rng.choice(sorted(CREDENTIAL_GENERATORS))
            blocks.append(CREDENTIAL_GENERATORS[kind](rng))
    text = "\n".join(blocks)[: 256 * 1024]
    dset = default_detector_set(
        dictionaries=(
            CustomerDictionary(
                dictionary_id="names",
                terms=("Project Falcon", "Bluebird"),
                sensitivity_category="cui",
            ),
        ),
        patterns=(
            CustomerPattern(pattern_id="emp", pattern="EMP-[0-9]{6}", sensitivity_category="pii"),
            CustomerPattern(
                pattern_id="case",
                pattern="(?i)case-[0-9]{4,10}",
                sensitivity_category="legal_privileged",
            ),
        ),
    )
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        result = _run(text, detector_set=dset)
        best = min(best, time.perf_counter() - started)
        assert isinstance(result, Redacted)
    assert best < 2.0, best


def test_credential_categories_cover_secret_detectors() -> None:
    for detector in secret_detectors():
        assert detector.always_redact
        assert detector.kinds <= CREDENTIAL_CATEGORIES | {"other"}


def test_chained_assignment_labels_leave_no_value() -> None:
    leaked = 0
    for seed in range(20):
        cred = CREDENTIAL_GENERATORS["client_secret_assignment"](random.Random(seed))
        secret = secret_value("client_secret_assignment", cred)
        result = _ok(f"password: {cred}")
        leaked += secret in result.text
    assert leaked == 0
