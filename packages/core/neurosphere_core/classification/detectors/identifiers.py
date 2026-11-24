"""Structured-identifier detectors with checksums (PRP-101 item 3).

Pure and deterministic: no I/O, no logging, and nothing here raises with input text. Each
detector returns offsets plus a category; candidates found by a bounded regex are confirmed by
a checksum or structure rule where the identifier has one (Luhn for cards, ISO 13616 mod 97
for IBANs, area/group/serial rules for US SSNs, the stdlib ``ipaddress`` parser for IPs).

Every pattern is linear-time safe: quantifiers are bounded or unambiguous, and each pattern
opens with a lookbehind that refuses to start inside a longer word or digit run, so a long
adversarial run costs one failed attempt per position.

Precision limits (documented, not bugs):
- US SSNs are only recognised with ``-`` or single-space separators; bare 9-digit runs are
  not reported (too many order numbers, zip+4 and counts look the same).
- Phone numbers are low precision: any separated ``2-4 / 3-4 / 4`` digit group or an E.164
  ``+`` run is reported, so some reference numbers will match.
- A 4-part version string such as ``1.2.3.4`` is a valid IPv4 address and is reported.
- Adjacent digit groups merge into one card candidate (``4111 ... 1111 2`` is checked as
  one 17-digit number), so a card directly followed by a separated digit can be missed.
- The Cisco ``xxxx.xxxx.xxxx`` MAC form needs at least one hex letter; all-digit Cisco MACs
  are not reported (they are indistinguishable from dotted phone numbers).
- Input is assumed normalised by the engine (NFKC, zero-width removal); only ASCII digits
  are recognised.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Final

from neurosphere_core.classification.models import Category, Confidence, Match
from neurosphere_core.classification.protocol import Detector

_VERSION: Final = "1.0.0"


class _PatternDetector:
    """Shared shape: one or more bounded patterns, each candidate confirmed by ``_accept``."""

    detector_id: str = ""
    version: str = _VERSION
    kinds: frozenset[str] = frozenset()
    always_redact: bool = False

    _category: Category = "other"
    _confidence: Confidence = "low"
    _patterns: tuple[re.Pattern[str], ...] = ()

    def find(self, text: str) -> tuple[Match, ...]:
        spans: set[tuple[int, int]] = set()
        for pattern in self._patterns:
            for m in pattern.finditer(text):
                span = self._accept(m)
                if span is not None:
                    spans.add(span)
        # Drop a span contained in another span of this detector (an IPv4 tail inside an
        # IPv4-mapped IPv6 address); one pass over spans sorted by start, longest first.
        kept: list[Match] = []
        reach = -1
        for start, end in sorted(spans, key=lambda s: (s[0], -s[1])):
            if end <= reach:
                continue
            reach = end
            kept.append(
                Match(
                    start=start,
                    end=end,
                    category=self._category,
                    confidence=self._confidence,
                    detector_id=self.detector_id,
                )
            )
        return tuple(kept)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        return m.span()


# --- payment cards ---------------------------------------------------------------------------

_CARD_RE: Final = re.compile(
    # 13-19 digits, single space or hyphen allowed between digits; never starts or ends inside
    # a longer digit/word run (including a run continued after one separator), never after "+"
    # (E.164 phones) or "." (dotted numbers).
    r"(?<![\w+.])(?<![0-9][ -])(?:[0-9][ -]?){12,18}[0-9](?!\w)(?![ -][0-9])(?!\.[0-9])"
)


def luhn_valid(digits: str) -> bool:
    """Luhn (mod 10) check over an ASCII digit string."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


class PaymentCardDetector(_PatternDetector):
    detector_id = "payment_card"
    kinds = frozenset({"payment_card"})
    _category = "payment_card"
    _confidence = "high"
    _patterns = (_CARD_RE,)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        digits = "".join(c for c in m.group() if "0" <= c <= "9")
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            return m.span()
        return None


# --- IBAN ------------------------------------------------------------------------------------

_IBAN_RE: Final = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}"
    r"(?:[A-Z0-9]{11,30}|(?: [A-Z0-9]{4}){2,7}(?: [A-Z0-9]{1,4})?)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def iban_valid(compact: str) -> bool:
    """ISO 13616 check: 15-34 alphanumerics, moved-front remainder mod 97 equals 1."""
    if not 15 <= len(compact) <= 34 or not compact.isascii() or not compact.isalnum():
        return False
    rearranged = (compact[4:] + compact[:4]).upper()
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


class IbanDetector(_PatternDetector):
    detector_id = "iban"
    kinds = frozenset({"iban"})
    _category = "iban"
    _confidence = "high"
    _patterns = (_IBAN_RE,)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        candidate = m.group()
        start = m.start()
        if iban_valid(candidate.replace(" ", "")):
            return m.span()
        # A grouped candidate may have swallowed one short trailing word ("... 7034 and"):
        # retry once without it, only when that group is letters-only, so an invalid IBAN is
        # not rescued by a chance-valid prefix.
        cut = candidate.rfind(" ")
        if cut > 4 and candidate[cut + 1 :].isalpha():
            if iban_valid(candidate[:cut].replace(" ", "")):
                return start, start + cut
        return None


# --- US SSN ----------------------------------------------------------------------------------

_SSN_RE: Final = re.compile(
    # AAA-GG-SSSS or AAA GG SSSS with the same separator twice. Bare 9-digit runs are NOT
    # matched on purpose: too many false positives (order numbers, zip+4, counts).
    r"(?<![\w-])(?<![0-9] )"
    r"(?P<area>[0-9]{3})(?P<sep>[- ])(?P<group>[0-9]{2})(?P=sep)(?P<serial>[0-9]{4})"
    r"(?![\w-])(?! [0-9])"
)


class UsSsnDetector(_PatternDetector):
    detector_id = "us_ssn"
    kinds = frozenset({"us_ssn"})
    _category = "us_ssn"
    _confidence = "medium"
    _patterns = (_SSN_RE,)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        area = m.group("area")
        if area in {"000", "666"} or area[0] == "9":
            return None
        if m.group("group") == "00" or m.group("serial") == "0000":
            return None
        return m.span()


# --- email -----------------------------------------------------------------------------------

_EMAIL_RE: Final = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9_-])"
)


class EmailAddressDetector(_PatternDetector):
    detector_id = "email_address"
    kinds = frozenset({"email_address"})
    _category = "email_address"
    _confidence = "high"
    _patterns = (_EMAIL_RE,)


# --- phone (low precision) -------------------------------------------------------------------

_PHONE_E164_RE: Final = re.compile(r"(?<![\w+])\+[0-9]{8,15}(?!\w)(?![ .-][0-9])")
_PHONE_NATIONAL_RE: Final = re.compile(
    # Separators are required between groups, so dates (2026-11-24, 11/24/2026), versions
    # (1.2.3), SSNs (3-2-4), times and plain counts never match; the lookarounds refuse a start
    # or end inside a longer separated digit run (card groups, IPs, dotted versions).
    r"(?<![\w.+-])(?<![0-9][ .-])"
    r"(?:\+[0-9]{1,3}[ .-]?)?"
    r"(?:\([0-9]{2,4}\) ?|[0-9]{2,4}[ .-])"
    r"[0-9]{3,4}[ .-][0-9]{4}"
    r"(?!\w)(?![ .-][0-9])"
)


class PhoneNumberDetector(_PatternDetector):
    """E.164 and separated national formats. Low precision by design (confidence ``low``)."""

    detector_id = "phone_number"
    kinds = frozenset({"phone_number"})
    _category = "phone_number"
    _confidence = "low"
    _patterns = (_PHONE_E164_RE, _PHONE_NATIONAL_RE)


# --- IP addresses ----------------------------------------------------------------------------

_IPV4_RE: Final = re.compile(
    # Not inside a longer dotted number (1.2.3.4.5). The IPv4 tail of an IPv4-mapped IPv6
    # address also matches here and is dropped as contained in the IPv6 span.
    r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?!\w)(?!\.[0-9])"
)
_IPV6_RE: Final = re.compile(
    r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}"
    r"(?:(?:[0-9]{1,3}\.){3}[0-9]{1,3}|[0-9A-Fa-f]{1,4})?"
    r"(?![\w:])(?!\.\w)"
)


class IpAddressDetector(_PatternDetector):
    detector_id = "ip_address"
    kinds = frozenset({"ip_address"})
    _category = "ip_address"
    _confidence = "medium"
    _patterns = (_IPV4_RE, _IPV6_RE)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        candidate = m.group()
        try:
            if ":" in candidate:
                if not any(c in "0123456789abcdefABCDEF" for c in candidate):
                    return None  # a bare "::" in prose is not worth reporting
                ipaddress.IPv6Address(candidate)
            else:
                ipaddress.IPv4Address(candidate)  # rejects octets > 255 and leading zeros
        except ValueError:
            return None
        return m.span()


# --- MAC addresses ---------------------------------------------------------------------------

_MAC_RE: Final = re.compile(
    # Six hex pairs with one consistent separator; the lookarounds refuse a run of pairs inside
    # an IPv6 address (preceded or followed by another ":" group).
    r"(?<![\w:.-])[0-9A-Fa-f]{2}(?P<sep>[:-])[0-9A-Fa-f]{2}(?:(?P=sep)[0-9A-Fa-f]{2}){4}"
    r"(?![\w:-])"
)
_MAC_CISCO_RE: Final = re.compile(
    r"(?<![\w:.-])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![\w:-])(?!\.\w)"
)


class MacAddressDetector(_PatternDetector):
    detector_id = "mac_address"
    kinds = frozenset({"mac_address"})
    _category = "mac_address"
    _confidence = "high"
    _patterns = (_MAC_RE, _MAC_CISCO_RE)

    def _accept(self, m: re.Match[str]) -> tuple[int, int] | None:
        candidate = m.group()
        if "." in candidate and not any(c in "abcdefABCDEF" for c in candidate):
            return None  # all-digit dotted groups are phone-shaped, not reported as a MAC
        return m.span()


# --- GUID ------------------------------------------------------------------------------------

_GUID_RE: Final = re.compile(
    # Surrounding braces are allowed but never part of the span.
    r"(?<![\w-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![\w-])"
)


class GuidDetector(_PatternDetector):
    detector_id = "guid"
    kinds = frozenset({"guid"})
    _category = "guid"
    _confidence = "high"
    _patterns = (_GUID_RE,)


def identifier_detectors() -> tuple[Detector, ...]:
    """The structured-identifier detectors, one per category, in a fixed order."""
    return (
        PaymentCardDetector(),
        IbanDetector(),
        UsSsnDetector(),
        EmailAddressDetector(),
        PhoneNumberDetector(),
        IpAddressDetector(),
        MacAddressDetector(),
        GuidDetector(),
    )
