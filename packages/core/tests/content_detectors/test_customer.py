"""PRP-101 item 4: customer dictionaries and bounded customer patterns."""

from __future__ import annotations

import importlib
import re
import sys
import time
import tomllib
from pathlib import Path

import pytest
from neurosphere_core.classification import Detector, placeholder
from neurosphere_core.classification.detectors.customer import (
    MAX_TERMS,
    REFUSAL_DETAILS,
    CustomerDictionary,
    CustomerDictionaryDetector,
    CustomerPattern,
    CustomerPatternDetector,
    PatternRefused,
    build_customer_detectors,
    check_pattern_safety,
)
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[4]
_CONFIDENTIAL_TERM = "Project Nightingale"


def _dict(*terms: str, **kw: object) -> CustomerDictionaryDetector:
    return CustomerDictionaryDetector(
        CustomerDictionary(
            dictionary_id=str(kw.get("dictionary_id", "codenames")),
            terms=terms,
            sensitivity_category="cui",
        )
    )


def _spans(detector: Detector, text: str) -> list[tuple[int, int]]:
    return [(m.start, m.end) for m in detector.find(text)]


def _refusal(pattern: str) -> PatternRefused:
    with pytest.raises(PatternRefused) as info:
        check_pattern_safety(pattern)
    return info.value


# --- Python version pin -----------------------------------------------------------------


def test_python_range_pinned_for_private_parser() -> None:
    # The safety check reads re._parser; a new Python range must re-review it.
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.12,<3.14"
    assert (3, 12) <= sys.version_info[:2] < (3, 14)
    parser = importlib.import_module("re._parser")
    tree = parser.parse(r"(a+)+")
    assert str(next(iter(tree))[0]) == "MAX_REPEAT"
    assert hasattr(tree, "getwidth")
    assert hasattr(tree.state, "flags")


# --- static safety check ----------------------------------------------------------------

CATASTROPHIC = [
    (r"(a+)+$", "nested_quantifier"),
    (r"(a*)*b", "nested_quantifier"),
    (r"(a|a)*c", "quantified_alternation"),
    (r"(a|aa)+$", "quantified_alternation"),
    (r"(.*a){20}", "nested_quantifier"),
    (r"(\w+\s?)*$", "nested_quantifier"),
    (r"^(([a-z])+.)+[A-Z]([a-z])+$", "nested_quantifier"),
    (r"(x+x+)+y", "nested_quantifier"),
    (r"(a{2})+", "nested_quantifier"),
    (r"(\d{1,3}-){3}", "nested_quantifier"),
    (r"(ab|cd){2,4}", "quantified_alternation"),
]


@pytest.mark.parametrize(("pattern", "detail"), CATASTROPHIC)
def test_catastrophic_shapes_refused(pattern: str, detail: str) -> None:
    refused = _refusal(pattern)
    assert refused.reason_code == "pattern_unsafe"
    assert refused.detail == detail


REFUSED = [
    ("a" * 257, "too_long"),
    ("", "too_long"),
    ("(unclosed", "invalid"),
    ("[z-a]", "invalid"),
    ("(?x)a b", "flags"),
    ("(?s)a.b", "flags"),
    ("(?m)^ab", "flags"),
    ("(?a)ab", "flags"),
    ("(?s:a.b)", "flags"),
    (r"(a)\1", "backreference"),
    ("(?P<n>a)(?P=n)", "backreference"),
    ("(a)?(?(1)b|c)", "conditional"),
    ("a(?=b)", "lookaround"),
    ("a(?!b)", "lookaround"),
    ("(?<=a)b", "lookaround"),
    ("(?<!a)b", "lookaround"),
    (r"\w+x", "unbounded_repeat_cap"),
    (".*x", "unbounded_repeat_cap"),
    ("[a-z]+[0-9]", "unbounded_repeat_cap"),
    ("a{2,}", "unbounded_repeat_cap"),
    ("a{1,101}", "unbounded_repeat_cap"),
    ("a{101}", "unbounded_repeat_cap"),
    ("a++b", "unbounded_repeat_cap"),
    ("x?", "empty_match"),
    (r"\b", "empty_match"),
    ("a{0,5}", "empty_match"),
    ("^$", "empty_match"),
    (r"\w{1,64}\w{1,64}x", "too_complex"),
    ("a{1,32}a{1,32}x", "too_complex"),
    (r"[A-Z]{1,40}[0-9]{1,40}", "too_complex"),
    (r"(a|b){1,40}c", "too_complex"),
]


@pytest.mark.parametrize(("pattern", "detail"), REFUSED)
def test_unsafe_patterns_refused_with_detail(pattern: str, detail: str) -> None:
    refused = _refusal(pattern)
    assert refused.reason_code == "pattern_unsafe"
    assert refused.detail == detail
    assert detail in REFUSAL_DETAILS


def test_refusal_never_echoes_pattern() -> None:
    pattern = r"(NIGHTINGALE+)+"
    refused = _refusal(pattern)
    for rendered in (str(refused), repr(refused), *map(str, refused.args)):
        assert "NIGHTINGALE" not in rendered
    with pytest.raises(PatternRefused) as info:
        CustomerPattern(pattern_id="codename", pattern=pattern, sensitivity_category="cui")
    assert "NIGHTINGALE" not in str(info.value)
    assert info.value.detail == "nested_quantifier"


def test_ignorecase_flag_allowed() -> None:
    check_pattern_safety("(?i)emp-[0-9]{6}")
    check_pattern_safety("(?i:emp)-[0-9]{6}")


# --- valid patterns ---------------------------------------------------------------------


def test_valid_patterns_find_exact_offsets() -> None:
    emp = CustomerPatternDetector(
        CustomerPattern(
            pattern_id="employee-id", pattern="EMP-[0-9]{6}", sensitivity_category="pii"
        )
    )
    prj = CustomerPatternDetector(
        CustomerPattern(
            pattern_id="project-code",
            pattern="PRJ[A-Z]{3}[0-9]{4}",
            sensitivity_category="cui",
            confidence="high",
        )
    )
    text = "owner EMP-123456 on PRJABC1234, not EMP-12345 or PRJAB1234."
    found = emp.find(text)
    assert [(m.start, m.end) for m in found] == [(6, 16)]
    assert text[6:16] == "EMP-123456"
    m = found[0]
    assert m.category == "customer_identifier_pattern"
    assert m.sensitivity_category == "pii"
    assert m.confidence == "medium"
    assert m.detector_id == "customer-pattern.employee-id"
    assert _spans(prj, text) == [(20, 30)]
    assert prj.find(text)[0].confidence == "high"
    assert isinstance(emp, Detector)
    assert emp.version == "1.0.0"
    assert emp.kinds == frozenset({"customer_identifier_pattern"})
    assert emp.always_redact is False


def test_pattern_skips_placeholder_interiors() -> None:
    det = CustomerPatternDetector(
        CustomerPattern(pattern_id="words", pattern="[a-z_]{5,20}", sensitivity_category="other")
    )
    text = f"{placeholder('email_address')} hello"
    assert _spans(det, text) == [(len(text) - 5, len(text))]


def test_pattern_model_validation_errors() -> None:
    with pytest.raises(ValidationError):
        CustomerPattern(pattern_id="Bad Id", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    with pytest.raises(ValidationError):
        CustomerPattern(
            pattern_id="ok",
            pattern="EMP-[0-9]{6}",
            sensitivity_category="pii",
            extra="x",  # type: ignore[call-arg]
        )


# --- timing: the check's rules bound the cost -------------------------------------------

FUZZ = [
    r"EMP-[0-9]{6}",
    r"PRJ[A-Z]{3}[0-9]{4}",
    r"[A-Z]{2}[0-9]{6,10}",
    r"[0-9]{4}(-[0-9]{4}){3}",
    r"(?i)acct-[a-z0-9]{8}",
    r"\w{1,64}x",
    r"\w{1,32}",
    r"\w{100}",
    r"[a-z]{1,30}[0-9]",
    r"a{1,30}b",
    r"a{1,20}a{1,20}b",
    r"(ab){1,30}c",
    r"(abc){5}",
    r"\d{3}-\d{2}-\d{4}",
    r"[A-Z][a-z]{1,20} [A-Z][a-z]{1,20}",
    r"x{1,50}y{1,10}",
    r"\s{1,10}a",
    r".{1,40}z",
    r"[^z]{1,40}z",
    r"(a|b){1,40}c",
    r"(foo|bar|baz)-[0-9]{4}",
    r"(a|aa)b",
    r"(a{1,10}|b)?c",
    r"a?b",
    r"(-[0-9]{1,4})?[A-Z]{3}",
    r"\bINV[0-9]{8}\b",
    r"^[A-Z]{4}$",
    r"[\w.]{1,30}@corp",
    r"\d{1,3}\.\d{1,3}\.\d{1,3}",
    r"ID:[ ]?[0-9]{5}",
    r"(?i)secret-[a-z]{1,16}",
    r"[aA]{1,60}!",
    r"a{100}",
    r"(xy){1,20}z",
    r"q[a-z]{1,40}q",
    r"[0-9a-f]{32}",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}",
    r"a.{1,30}b",
    r"\D{1,30}1",
    r"\S{1,40}\s",
    r"(a+)+$",
    r"(a*)*b",
    r"(a|a)*c",
    r"(a|aa)+$",
    r"(.*a){20}",
    r"(\w+\s?)*$",
    r"^(([a-z])+.)+[A-Z]([a-z])+$",
    r"(x+x+)+y",
    r"\w+\w+x",
    r"a{1,64}a{1,64}a{1,64}b",
    r"[A-Z]{3}-[0-9]{3}",
    r"CASE#[0-9]{7}",
    r"[a-z]{1,8}@acme",
    r"(?i)vendor_[0-9]{4}",
    r"[0-9]{2}/[0-9]{2}/[0-9]{4}",
    r"\d{1,20}",
    r"BADGE[0-9]{5,7}",
    r"[A-Z]{2,5}-[0-9]{2,5}",
]

_N = 64 * 1024
ADVERSARIAL = {
    "a": "a" * _N,
    "x": "x" * _N,
    "digits": "1" * _N,
    "spaces": " " * _N,
    "word_space": ("a " * _N)[:_N],
    "ab": ("ab" * _N)[:_N],
    "mixed": ("aB3-_ x.Q" * _N)[:_N],
    "upper": "A" * _N,
    "q": "q" * _N,
    "digit_alpha": ("1a" * _N)[:_N],
    "dots": ("a." * _N)[:_N],
}


def _accepted(pattern: str) -> bool:
    try:
        check_pattern_safety(pattern)
    except PatternRefused:
        return False
    return True


def test_fuzz_list_has_both_outcomes() -> None:
    accepted = [p for p in FUZZ if _accepted(p)]
    assert len(FUZZ) >= 50
    assert len(accepted) >= 30
    assert len(FUZZ) - len(accepted) >= 10


@pytest.mark.parametrize("pattern", [p for p in FUZZ if _accepted(p)])
def test_accepted_patterns_run_fast_on_adversarial_text(pattern: str) -> None:
    compiled = re.compile(pattern)
    for text in ADVERSARIAL.values():
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            for _m in compiled.finditer(text):
                pass
            best = min(best, time.perf_counter() - started)
            if best < 0.05:
                break
        assert best < 0.05


# --- dictionary -------------------------------------------------------------------------


def test_dictionary_case_folded_word_bounded() -> None:
    det = _dict("acme", "Blue Sky", "R&D-7")
    text = "ACME met acmes and xacme; BLUE   sky vs blue sky. r&d-7 done, ar&d-7x"
    spans = _spans(det, text)
    assert [text[s:e] for s, e in spans] == ["ACME", "blue sky", "r&d-7"]
    assert spans[0] == (0, 4)


def test_dictionary_longest_term_wins() -> None:
    det = _dict("blue", "blue sky", "sky")
    text = "the blue sky and sky"
    assert [text[s:e] for s, e in _spans(det, text)] == ["blue sky", "sky"]


def test_dictionary_offsets_survive_casefold_length_change() -> None:
    det = _dict("acme", "strasse")
    text = "Straße ß ACME, STRASSE."
    spans = _spans(det, text)
    assert [text[s:e] for s, e in spans] == ["Straße", "ACME", "STRASSE"]
    assert spans == [(0, 6), (9, 13), (15, 22)]


def test_dictionary_does_not_match_half_a_fold() -> None:
    det = _dict("s")
    assert _spans(det, "ß s") == [(2, 3)]


def test_dictionary_match_fields() -> None:
    det = CustomerDictionaryDetector(
        CustomerDictionary(
            dictionary_id="codenames", terms=("acme",), sensitivity_category="export_controlled"
        )
    )
    (m,) = det.find("acme")
    assert m.category == "customer_dictionary_term"
    assert m.sensitivity_category == "export_controlled"
    assert m.confidence == "high"
    assert m.detector_id == "customer-dict.codenames"
    assert det.version == "1.0.0"
    assert det.kinds == frozenset({"customer_dictionary_term"})
    assert det.always_redact is False
    assert isinstance(det, Detector)


def test_dictionary_terms_stripped_and_deduplicated() -> None:
    d = CustomerDictionary(
        dictionary_id="d", terms=("  Acme ", "ACME", "acme", "Other"), sensitivity_category="pii"
    )
    assert d.terms == ("Acme", "Other")


@pytest.mark.parametrize(
    "terms",
    [
        (),
        ("   ",),
        (_CONFIDENTIAL_TERM, "x" * 257),
        tuple(f"{_CONFIDENTIAL_TERM} {i}" for i in range(MAX_TERMS + 1)),
    ],
)
def test_dictionary_caps_do_not_echo_terms(terms: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError) as info:
        CustomerDictionary(dictionary_id="d", terms=terms, sensitivity_category="pii")
    assert "Nightingale" not in str(info.value)
    assert "xxxx" not in str(info.value)


def test_dictionary_accepts_max_terms() -> None:
    terms = tuple(f"term{i}" for i in range(MAX_TERMS))
    det = _dict(*terms)
    assert _spans(det, "x term9999 y") == [(2, 10)]


def test_placeholder_not_matched_unless_listed_literally() -> None:
    ph = placeholder("email_address")
    text = f"mail {ph} redacted"
    det = _dict("email_address", "ns", "redacted")
    assert [text[s:e] for s, e in _spans(det, text)] == ["redacted"]
    literal = _dict(ph)
    assert _spans(literal, text) == [(5, 5 + len(ph))]


def test_dictionary_scan_is_bounded_on_adversarial_text() -> None:
    long_term = ("a " * 127) + "b"
    det = _dict(long_term, "a")
    text = ("a " * _N)[:_N]
    started = time.perf_counter()
    found = det.find(text)
    elapsed = time.perf_counter() - started
    assert len(found) == _N // 2
    assert elapsed < 5.0


def test_detector_ids_stay_within_slug_limit() -> None:
    slug = "a" * 64
    det = _dict("acme", dictionary_id=slug)
    pat = CustomerPatternDetector(
        CustomerPattern(pattern_id=slug, pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    )
    other = _dict("acme", dictionary_id=("a" * 63) + "b")
    for d in (det, pat, other):
        assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", d.detector_id)
    assert det.detector_id != other.detector_id


def test_detector_reprs_hide_terms_and_patterns() -> None:
    det = _dict(_CONFIDENTIAL_TERM)
    pat = CustomerPatternDetector(
        CustomerPattern(pattern_id="p", pattern="NIGHT-[0-9]{6}", sensitivity_category="pii")
    )
    assert "Nightingale" not in repr(det)
    assert "NIGHT" not in repr(pat)
    assert "customer-dict.codenames" in repr(det)
    matches = det.find(f"about {_CONFIDENTIAL_TERM} now")
    assert len(matches) == 1
    assert "Nightingale" not in repr(matches)


def test_build_customer_detectors() -> None:
    d = CustomerDictionary(dictionary_id="d", terms=("acme",), sensitivity_category="pii")
    p = CustomerPattern(pattern_id="p", pattern="EMP-[0-9]{6}", sensitivity_category="pii")
    built = build_customer_detectors([d], [p])
    assert [x.detector_id for x in built] == ["customer-dict.d", "customer-pattern.p"]
    assert build_customer_detectors([], []) == ()
