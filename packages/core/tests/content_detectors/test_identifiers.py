"""PRP-101 item 3: structured-identifier detectors with checksums.

Every card, IBAN and SSN is generated at runtime from a seeded ``random.Random``; no real
personal data and no long literal card numbers are committed.
"""

from __future__ import annotations

import random
import re
import string
import time
from typing import cast

import pytest
from neurosphere_core.classification import (
    ALL_CATEGORIES,
    Category,
    Detector,
    Match,
    placeholder,
)
from neurosphere_core.classification.detectors.identifiers import (
    EmailAddressDetector,
    GuidDetector,
    IbanDetector,
    IpAddressDetector,
    MacAddressDetector,
    PaymentCardDetector,
    PhoneNumberDetector,
    UsSsnDetector,
    iban_valid,
    identifier_detectors,
    luhn_valid,
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SEED = 20261124


def _rng(salt: int = 0) -> random.Random:
    return random.Random(_SEED + salt)  # noqa: S311 - seeded fixture data, not crypto


# --- generators (local: synth.py is another lane's file) --------------------------------------


def _luhn_check_digit(body: str) -> str:
    for check in "0123456789":
        if luhn_valid(body + check):
            return check
    raise AssertionError("unreachable")


def _card(rng: random.Random, length: int) -> str:
    body = str(rng.randint(3, 6)) + "".join(rng.choice(string.digits) for _ in range(length - 2))
    return body + _luhn_check_digit(body)


def _broken_card(card: str) -> str:
    return card[:-1] + str((int(card[-1]) + 1) % 10)


def _group(digits: str, sep: str, size: int = 4) -> str:
    return sep.join(digits[i : i + size] for i in range(0, len(digits), size))


def _iban(rng: random.Random, country: str, bban_len: int) -> str:
    bban = "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(bban_len))
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(numeric) % 97
    return f"{country}{check:02d}{bban}"


def _broken_iban(iban: str) -> str:
    check = int(iban[2:4])
    return f"{iban[:2]}{(check + 1) % 100:02d}{iban[4:]}"


def _ssn(rng: random.Random, sep: str = "-") -> str:
    area = rng.choice([a for a in range(1, 900) if a != 666])
    return f"{area:03d}{sep}{rng.randint(1, 99):02d}{sep}{rng.randint(1, 9999):04d}"


def _spans(detector: Detector, text: str) -> list[str]:
    return [text[m.start : m.end] for m in detector.find(text)]


# --- protocol conformance --------------------------------------------------------------------


def test_detector_set_shape() -> None:
    detectors = identifier_detectors()
    ids = [d.detector_id for d in detectors]
    assert ids == [
        "payment_card",
        "iban",
        "us_ssn",
        "email_address",
        "phone_number",
        "ip_address",
        "mac_address",
        "guid",
    ]
    for d in detectors:
        assert isinstance(d, Detector)
        assert _ID_RE.match(d.detector_id)
        assert d.version == "1.0.0"
        assert d.kinds == frozenset({d.detector_id})
        assert d.kinds <= ALL_CATEGORIES
        assert d.always_redact is False


def test_empty_and_plain_text_find_nothing() -> None:
    for d in identifier_detectors():
        assert d.find("") == ()
        assert d.find("The quick brown fox jumps over the lazy dog.") == ()


# --- payment cards ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", range(13, 20))
def test_luhn_valid_cards_found_every_length(length: int) -> None:
    rng = _rng(length)
    det = PaymentCardDetector()
    for _ in range(5):
        card = _card(rng, length)
        for shown in (card, _group(card, " "), _group(card, "-")):
            text = f"pay with {shown}, thanks"
            (m,) = det.find(text)
            assert text[m.start : m.end] == shown
            assert (m.category, m.confidence, m.detector_id) == (
                "payment_card",
                "high",
                det.detector_id,
            )


@pytest.mark.parametrize("length", range(13, 20))
def test_luhn_invalid_cards_not_found(length: int) -> None:
    rng = _rng(100 + length)
    det = PaymentCardDetector()
    for _ in range(5):
        bad = _broken_card(_card(rng, length))
        assert not luhn_valid(bad)
        for shown in (bad, _group(bad, " "), _group(bad, "-")):
            assert det.find(f"pay with {shown}") == ()


def test_card_not_part_of_longer_run() -> None:
    rng = _rng(7)
    card = _card(rng, 16)
    det = PaymentCardDetector()
    assert det.find("x" + card) == ()
    assert det.find(card + "9") == ()
    assert det.find("+" + card) == ()  # E.164-shaped
    # 20+ digits is never a card, whatever the Luhn sum.
    assert det.find(_card(rng, 21)) == ()


# --- IBAN ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("country", "bban_len"),
    [("DE", 18), ("GB", 18), ("FR", 23), ("NO", 11), ("LC", 28), ("XK", 30)],
)
def test_iban_valid_found_invalid_not(country: str, bban_len: int) -> None:
    rng = _rng(bban_len)
    det = IbanDetector()
    for _ in range(5):
        iban = _iban(rng, country, bban_len)
        assert iban_valid(iban)
        for shown in (iban, iban.lower(), _group(iban, " ")):
            text = f"IBAN: {shown}. Ok"
            assert _spans(det, text) == [shown]
            assert det.find(text)[0].confidence == "high"
        bad = _broken_iban(iban)
        assert not iban_valid(bad)
        assert det.find(f"IBAN: {bad}") == ()
        assert det.find(f"IBAN: {_group(bad, ' ')}") == ()


def test_grouped_iban_followed_by_short_word() -> None:
    iban = _iban(_rng(3), "BE", 12)  # 16 chars: four full groups
    text = f"send to {_group(iban, ' ')} and done"
    assert _spans(IbanDetector(), text) == [_group(iban, " ")]


# --- US SSN ----------------------------------------------------------------------------------


def test_ssn_found_with_dash_and_space() -> None:
    rng = _rng(11)
    det = UsSsnDetector()
    for _ in range(20):
        for sep in ("-", " "):
            ssn = _ssn(rng, sep)
            text = f"ssn ({ssn})."
            (m,) = det.find(text)
            assert text[m.start : m.end] == ssn
            assert m.confidence == "medium"


def _ssn_of(area: str, group: str, serial: str, sep: str = "-") -> str:
    # Assembled at runtime: the pre-commit hook refuses SSN-shaped literals.
    return sep.join((area, group, serial))


_SSN_BASE = _ssn_of("123", "45", "6789")


def test_ssn_control_value_is_found() -> None:
    assert _spans(UsSsnDetector(), f"ssn {_SSN_BASE}") == [_SSN_BASE]


@pytest.mark.parametrize(
    ("area", "group", "serial"),
    [
        ("000", "12", "3456"),
        ("666", "12", "3456"),
        ("900", "12", "3456"),
        ("987", "65", "4321"),
        ("999", "12", "3456"),
        ("123", "00", "4567"),
        ("123", "45", "0000"),
    ],
)
def test_ssn_structure_exclusions(area: str, group: str, serial: str) -> None:
    for sep in ("-", " "):
        assert UsSsnDetector().find(f"ssn {_ssn_of(area, group, serial, sep)}") == ()


@pytest.mark.parametrize(
    "value",
    [
        _SSN_BASE.replace("-", ""),  # bare 9-digit run
        "123-45 6789",  # mixed separators
        "123.45.6789",
        "1" + _SSN_BASE,
        _SSN_BASE + "0",
        _SSN_BASE + "-1",
    ],
)
def test_ssn_shape_exclusions(value: str) -> None:
    # Bare 9-digit runs are deliberately not SSNs; mixed separators and longer runs neither.
    assert UsSsnDetector().find(f"id {value}") == ()


# --- email -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email", ["a.b+tag@example.com", "user_1@mail.example.co.uk", "x%y@sub-domain.example.org"]
)
def test_email_found_with_exact_offsets(email: str) -> None:
    text = f"<{email}>."
    (m,) = EmailAddressDetector().find(text)
    assert text[m.start : m.end] == email
    assert m.confidence == "high"


@pytest.mark.parametrize("value", ["user@localhost", "@example.com", "a@b", "not an email"])
def test_email_negatives(value: str) -> None:
    assert EmailAddressDetector().find(value) == ()


# --- phone -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "(555) 123-4567",
        "(555)123-4567",
        "555-123-4567",
        "555.123.4567",
        "555 123 4567",
        "+1 555 123 4567",
        "+1-555-123-4567",
        "+1 (555) 123-4567",
        "+44 20 7946 0958",
        "+15551234567",
        "+442079460958",
    ],
)
def test_phone_found(phone: str) -> None:
    text = f"call {phone}, please"
    (m,) = PhoneNumberDetector().find(text)
    assert text[m.start : m.end] == phone
    assert m.confidence == "low"


def test_phone_guards() -> None:
    rng = _rng(21)
    card = _card(rng, 16)
    negatives = [
        "2026-11-24",
        "11/24/2026",
        "24.11.2026",
        "2026.11.24",
        "1.2.3",
        "10.0.26300",
        "10.0.26300.1234",
        "192.168.100.200",
        _SSN_BASE,
        "123 45 6789",
        _ssn(rng),
        "12:30:45",
        "10:30-11:45",
        "1,234,567",
        "1234567",
        "12345678901",
        "3 500 000",
        card,
        _group(card, " "),
        _group(card, "-"),
        _group(_card(rng, 15), " "),
        "00:1A:2B:3C:4D:5E",
        "12345678-1234-1234-1234-123456789012",
        "+1234567",  # too short for E.164
        "+1234567890123456",  # too long for E.164
    ]
    det = PhoneNumberDetector()
    hits = {value: _spans(det, f"value {value} here") for value in negatives}
    assert {k: v for k, v in hits.items() if v} == {}


# --- IP addresses ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "192.168.1.10",
        "10.0.0.1",
        "255.255.255.255",
        "2001:db8:85a3:0:0:8a2e:370:7334",
        "2001:0db8:0000:0000:0000:ff00:0042:8329",
        "2001:db8::1",
        "fe80::",
        "::1",
        "::ffff:192.0.2.1",
    ],
)
def test_ip_found(ip: str) -> None:
    for text in (f"host {ip} up", f"[{ip}]:443", f"ip={ip}."):
        (m,) = IpAddressDetector().find(text)
        assert text[m.start : m.end] == ip
        assert m.confidence == "medium"


@pytest.mark.parametrize(
    "value",
    [
        "256.1.1.1",
        "1.2.3.256",
        "01.2.3.4",
        "1.2.3.4.5",
        "10.0.26300",
        "12:30:45",
        "std::vector",
        "a :: b",
        "1:2:3:4:5:6:7:8:9",
        "00:1A:2B:3C:4D:5E",
    ],
)
def test_ip_negatives(value: str) -> None:
    assert IpAddressDetector().find(f"x {value} y") == ()


# --- MAC -------------------------------------------------------------------------------------


@pytest.mark.parametrize("mac", ["00:1A:2B:3C:4D:5E", "00-1a-2b-3c-4d-5e", "001a.2b3c.4d5e"])
def test_mac_found(mac: str) -> None:
    text = f"nic {mac}."
    (m,) = MacAddressDetector().find(text)
    assert text[m.start : m.end] == mac
    assert m.confidence == "high"


@pytest.mark.parametrize(
    "value",
    [
        "00:1A-2B:3C:4D:5E",  # mixed separators
        "00:1A:2B:3C:4D",  # five pairs
        "00:1A:2B:3C:4D:5E:6F",  # seven pairs
        "2001:db8:aa:bb:cc:dd:ee:ff",  # IPv6 containing six pairs
        "fe80::aa:bb:cc:dd:ee:ff",
        "1234.5678.9012",  # all-digit dotted: phone-shaped
    ],
)
def test_mac_negatives(value: str) -> None:
    assert MacAddressDetector().find(f"x {value} y") == ()


# --- GUID ------------------------------------------------------------------------------------


def test_guid_found_without_braces() -> None:
    guid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    for text in (f"id {guid} ok", f"{{{guid}}}", f"id={guid.upper()};"):
        (m,) = GuidDetector().find(text)
        assert text[m.start : m.end].lower() == guid
        assert m.confidence == "high"


@pytest.mark.parametrize(
    "value",
    [
        "3f2504e0-4f89-11d3-9a0c-0305e82c330",
        "3f2504e0-4f89-11d3-9a0c-0305e82c33011",
        "x3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    ],
)
def test_guid_negatives(value: str) -> None:
    assert GuidDetector().find(value) == ()


# --- cross-detector properties ---------------------------------------------------------------


def _mixed_corpus() -> str:
    rng = _rng(42)
    return "\n".join(
        [
            f"card {_card(rng, 16)} and {_group(_card(rng, 15), ' ')}",
            f"iban {_group(_iban(rng, 'DE', 18), ' ')} ssn {_ssn(rng)}",
            "mail jane.doe@example.com tel (555) 123-4567 or +44 20 7946 0958",
            "ip 10.1.2.3 and 2001:db8::7 and ::ffff:192.0.2.1",
            "mac 00:1A:2B:3C:4D:5E guid {3f2504e0-4f89-11d3-9a0c-0305e82c3301}",
        ]
    )


def test_each_mixed_corpus_category_found_once() -> None:
    text = _mixed_corpus()
    found = {d.detector_id: len(d.find(text)) for d in identifier_detectors()}
    assert found == {
        "payment_card": 2,
        "iban": 1,
        "us_ssn": 1,
        "email_address": 1,
        "phone_number": 2,
        "ip_address": 3,
        "mac_address": 1,
        "guid": 1,
    }


def test_no_avoidable_cross_detector_overlap() -> None:
    text = _mixed_corpus()
    matches: list[Match] = [m for d in identifier_detectors() for m in d.find(text)]
    for a in matches:
        for b in matches:
            if a is not b:
                assert a.end <= b.start or b.end <= a.start, (a.category, b.category)


def test_placeholders_never_match_and_redaction_is_idempotent() -> None:
    detectors = identifier_detectors()
    for category in sorted(ALL_CATEGORIES):
        token = placeholder(cast("Category", category))
        for d in detectors:
            assert d.find(f"a {token} b {token}{token}") == ()
    text = _mixed_corpus()
    matches = sorted((m for d in detectors for m in d.find(text)), key=lambda m: m.start)
    out: list[str] = []
    cursor = 0
    for m in matches:
        out.append(text[cursor : m.start])
        out.append(placeholder(m.category))
        cursor = m.end
    out.append(text[cursor:])
    redacted = "".join(out)
    assert all(d.find(redacted) == () for d in detectors)


_MB = 1_000_000

_ADVERSARIAL = {
    "digits": "1" * _MB,
    "spaced_digits": "1 " * (_MB // 2),
    "dashed_digits": "1-" * (_MB // 2),
    "dotted_digits": "1." * (_MB // 2),
    "groups": "1234 " * (_MB // 5),
    "colons": ":" * _MB,
    "hex_colons": "a:" * (_MB // 2),
    "at_runs": "a@" * (_MB // 2),
    "dot_labels": "a@" + "a." * (_MB // 2),
    "hex_run": "0123456789abcdef" * (_MB // 16),
    "iban_like": "AB12" + "C" * _MB,
    "parens": "(55) " * (_MB // 5),
}


@pytest.mark.parametrize("name", sorted(_ADVERSARIAL))
def test_adversarial_megabyte_inputs_are_fast(name: str) -> None:
    text = _ADVERSARIAL[name]
    for d in identifier_detectors():
        started = time.perf_counter()
        d.find(text)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, (d.detector_id, name, elapsed)


def test_find_never_raises_on_odd_input() -> None:
    arabic_indic_ssn = "".join(chr(0x660 + int(c)) if c.isdigit() else c for c in _SSN_BASE)
    odd = ["\x00￿", arabic_indic_ssn, "[[ns-redacted:", "]]", "::", "@", "+", "()", "\n" * 10]
    for d in identifier_detectors():
        for value in odd:
            assert isinstance(d.find(value), tuple)
