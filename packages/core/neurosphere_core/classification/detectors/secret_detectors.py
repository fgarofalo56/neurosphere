"""Credential and secret detectors (PRP-101 item 2).

Every detector here is pure and deterministic, never logs and never raises with text: ``find``
returns offsets and a category only. Credential matches are always replaced (Clarification 3);
``opaque_secret`` reports category ``other`` at low confidence and is also always replaced
(Clarification 9).

Formats are limited to the "Sources" section of ``docs/runbooks/content-classification.md``:
the repo-carried rules (``copilot/models/redaction.py``, ``tests/contracts/validators.py``
``SECRET_TEXT_PATTERNS``) and the verified external formats 1-8. Nothing else is coded.

Spans are chosen so that replacing them with ``[[ns-redacted:<category>]]`` leaves no key
fragment and nothing the PRP-99 ``secret_free_text`` rule rejects: a URL with userinfo is
spanned from the scheme through the ``@``; a connection string, SAS token or SAS URL is spanned
as the whole delimited token; labelled values (``Bearer``, ``password=``, ``api-key:``) keep
the label and span the value. No detector matches a placeholder (idempotence).

Linear time: every pattern starts at a literal, is anchored by a negative lookbehind so a run
is scanned once, or uses bounded quantifiers; expansion to token boundaries is done in code and
never rescans a region already covered.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Final

from neurosphere_core.classification.models import Category, Confidence, Match
from neurosphere_core.classification.protocol import Detector

__all__ = [
    "BearerTokenDetector",
    "CloudAccessKeyDetector",
    "ConnectionStringDetector",
    "JwtDetector",
    "OpaqueSecretDetector",
    "PasswordAssignmentDetector",
    "PrivateKeyDetector",
    "UrlWithCredentialsDetector",
    "VendorApiKeyDetector",
    "secret_detectors",
]

_VERSION: Final = "1.0.0"
_PLACEHOLDER_START: Final = "[[ns-redacted:"


class _Base:
    """Shared attributes; subclasses set the id, category, confidence and ``find``."""

    detector_id: str = ""
    version: str = _VERSION
    kinds: frozenset[str] = frozenset()
    always_redact: bool = True
    _category: Category = "other"
    _confidence: Confidence = "high"
    _sensitivity: str | None = None

    def _match(self, start: int, end: int) -> Match:
        return Match(
            start=start,
            end=end,
            category=self._category,
            confidence=self._confidence,
            detector_id=self.detector_id,
            sensitivity_category=self._sensitivity,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(detector_id={self.detector_id!r})"


# --- private_key -------------------------------------------------------------------------

_PEM_BEGIN: Final = re.compile(r"-{5}BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-{5}")
_PEM_END: Final = re.compile(r"-{5}END [A-Z0-9 ]{0,40}PRIVATE KEY-{5}")


class PrivateKeyDetector(_Base):
    """``-----BEGIN ... PRIVATE KEY-----`` through the matching END line, else to end of text."""

    detector_id = "private_key"
    kinds = frozenset({"private_key"})
    _category = "private_key"

    def find(self, text: str) -> tuple[Match, ...]:
        out: list[Match] = []
        pos = 0
        while True:
            begin = _PEM_BEGIN.search(text, pos)
            if begin is None:
                break
            end = _PEM_END.search(text, begin.end())
            stop = len(text) if end is None else end.end()
            out.append(self._match(begin.start(), stop))
            if end is None:
                break
            pos = stop
        return tuple(out)


# --- jwt ---------------------------------------------------------------------------------

#: Whole base64url runs (lookbehind: a run is entered once at its start; possessive runs never
#: give back). The ``eyJ`` header is checked in code, so ``x``/``token_`` glued in front of a
#: token does not hide it (``secret_free_text`` has no left boundary either).
_JWT: Final = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<head>[A-Za-z0-9_-]{7,}+)\.[A-Za-z0-9_-]{4,}+(?:\.[A-Za-z0-9_-]*+)?"
)
_JWT_HEADER: Final = "eyJ"
_JWT_MIN_HEADER_TAIL: Final = 4


class JwtDetector(_Base):
    """``eyJ`` header, payload and optional signature (base64url segments).

    The span starts at the first ``eyJ`` of the first segment that holds ``eyJ`` plus at least
    4 more characters. A rejected candidate is retried from its second segment, so a JWT glued
    after ``name.part.`` is still found; each segment is scanned a bounded number of times.
    """

    detector_id = "jwt"
    kinds = frozenset({"jwt"})
    _category = "jwt"

    def find(self, text: str) -> tuple[Match, ...]:
        out: list[Match] = []
        pos = 0
        while True:
            m = _JWT.search(text, pos)
            if m is None:
                break
            head = m.group("head")
            at = head.find(_JWT_HEADER)
            if at >= 0 and len(head) - at - len(_JWT_HEADER) >= _JWT_MIN_HEADER_TAIL:
                out.append(self._match(m.start() + at, m.end()))
                pos = m.end()
            else:
                pos = m.end("head") + 1
        return tuple(out)


# --- bearer_token ------------------------------------------------------------------------

#: The span is the token only; the word ``Bearer`` is kept. The token class excludes ``[``, so
#: ``Bearer [[ns-redacted:...]]`` matches neither here nor in ``secret_free_text``. No left
#: boundary and an unbounded possessive blank run, mirroring ``secret_free_text`` exactly.
_BEARER: Final = re.compile(r"(?i)bearer[ \t]++(?P<token>[A-Za-z0-9._~+/=-]{8,}+)")


class BearerTokenDetector(_Base):
    """Case-insensitive ``bearer`` plus a token of 8 or more token characters."""

    detector_id = "bearer_token"
    kinds = frozenset({"bearer_token"})
    _category = "bearer_token"

    def find(self, text: str) -> tuple[Match, ...]:
        return tuple(self._match(m.start("token"), m.end("token")) for m in _BEARER.finditer(text))


# --- cloud_access_key --------------------------------------------------------------------

#: No left boundary, mirroring ``secret_free_text`` (recall first).
_AWS: Final = re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")


class CloudAccessKeyDetector(_Base):
    """AWS access key ids: ``AKIA`` or ``ASIA`` plus 16 uppercase letters or digits."""

    detector_id = "cloud_access_key"
    kinds = frozenset({"cloud_access_key"})
    _category = "cloud_access_key"

    def find(self, text: str) -> tuple[Match, ...]:
        return tuple(self._match(m.start(), m.end()) for m in _AWS.finditer(text))


# --- vendor_api_key ----------------------------------------------------------------------

#: GitHub prefixes take any length (``ghs_APPID_JWT`` stateless tokens contain ``_`` and ``.``).
_GITHUB: Final = re.compile(r"gh[pousr]_[A-Za-z0-9_.-]{16,}|github_pat_[A-Za-z0-9_]{16,}")
#: ``sk``/``pk`` keys need a left boundary (``task-``, ``disk-`` are not keys) and, checked in
#: code, a digit or uppercase letter in the body (``pk_customer_order_id`` is a column name).
_SK_PK: Final = re.compile(r"(?<![A-Za-z0-9])(?:sk|pk)[-_](?P<body>[A-Za-z0-9_-]{16,})")
#: The ``secret_free_text`` ``sk-`` rule, mirrored exactly (no left boundary, no case gate), so
#: no output that rule rejects survives. It also hits ``disk-encryption-...`` style slugs, so
#: matches only this rule finds are reported at low confidence (accepted over-redaction).
_SK_DASH: Final = re.compile(r"sk-[A-Za-z0-9_-]{20,}+")
_SLACK: Final = re.compile(r"(?<![A-Za-z0-9])xox[bap][-_][A-Za-z0-9_-]{16,}")
#: Header and query-parameter context (source 6). The value is spanned, the label kept; a bare
#: 32-hex string is never matched. The value class excludes ``[`` (placeholders).
_KEY_CONTEXT: Final = re.compile(
    r"(?i)(?:ocp-apim-subscription-key|subscription-key|api-key)[\"']?[ \t]{0,4}[:=]"
    r"[ \t]{0,4}[\"']?(?P<value>[A-Za-z0-9%+/=_-]{16,512})"
)
_UPPER_OR_DIGIT: Final = re.compile(r"[A-Z0-9]")


class VendorApiKeyDetector(_Base):
    """GitHub tokens, ``sk-``/``sk_``/``pk_`` keys, Slack ``xox[bap]`` tokens and
    ``api-key`` / ``Ocp-Apim-Subscription-Key`` / ``subscription-key`` values."""

    detector_id = "vendor_api_key"
    kinds = frozenset({"vendor_api_key"})
    _category = "vendor_api_key"

    def find(self, text: str) -> tuple[Match, ...]:
        spans: set[tuple[int, int]] = set()
        for m in _GITHUB.finditer(text):
            end = m.end()
            while end > m.start() and text[end - 1] == ".":  # a sentence full stop
                end -= 1
            spans.add((m.start(), end))
        spans.update(
            (m.start(), m.end())
            for m in _SK_PK.finditer(text)
            if _UPPER_OR_DIGIT.search(m.group("body"))
        )
        spans.update((m.start(), m.end()) for m in _SLACK.finditer(text))
        spans.update((m.start("value"), m.end("value")) for m in _KEY_CONTEXT.finditer(text))
        low = {(m.start(), m.end()) for m in _SK_DASH.finditer(text)} - spans
        out = [self._match(s, e) for s, e in spans]
        out.extend(self._low(s, e) for s, e in low)
        return tuple(sorted(out, key=lambda m: (m.start, m.end)))

    def _low(self, start: int, end: int) -> Match:
        return Match(
            start=start,
            end=end,
            category=self._category,
            confidence="low",
            detector_id=self.detector_id,
            sensitivity_category=self._sensitivity,
        )


# --- connection_string -------------------------------------------------------------------

#: Anchors that carry key material. ``SharedAccessSignature sr=`` is the Event Hubs SAS token;
#: ``sig=`` is a storage or Event Hubs SAS signature (Clarification 10); like
#: ``secret_free_text`` it has no left boundary (``xsig=...`` is still a signature).
_CONN_ANCHOR: Final = re.compile(
    r"(?i)(?:AccountKey|SharedAccessKey|SharedAccessSignature)[ \t]{0,2}=[ \t]{0,2}"
    r"|SharedAccessSignature[ \t]{1,4}(?=sr=)"
    r"|sig="
)
#: Characters that end a connection-string token (whitespace, quotes, brackets, comma).
_TOKEN_STOP: Final = frozenset(" \t\r\n\f\v\"'`<>()[]{},")
_LEFT_EXPANSION_LIMIT: Final = 2048
_MIN_VALUE_CHARS: Final = 8


class ConnectionStringDetector(_Base):
    """Azure Storage, Event Hubs and Service Bus connection strings, ``AccountKey=`` and
    ``SharedAccessKey=`` assignments, Event Hubs SAS tokens and SAS ``sig=`` values.

    The span is the whole delimited token around the key material (a full connection string or
    SAS URL is one span), so no key fragment and no ``sig=`` survives redaction. The value must
    be at least 8 token characters; a placeholder value is empty (``[`` stops it).
    """

    detector_id = "connection_string"
    kinds = frozenset({"connection_string"})
    _category = "connection_string"

    def find(self, text: str) -> tuple[Match, ...]:
        out: list[Match] = []
        floor = 0  # nothing before this offset is re-spanned
        pos = 0
        size = len(text)
        while True:
            anchor = _CONN_ANCHOR.search(text, pos)
            if anchor is None:
                break
            value_end = anchor.end()
            while value_end < size and text[value_end] not in _TOKEN_STOP:
                value_end += 1
            if value_end - anchor.end() < _MIN_VALUE_CHARS:
                pos = anchor.end()
                continue
            start = anchor.start()
            limit = max(floor, start - _LEFT_EXPANSION_LIMIT)
            while start > limit and text[start - 1] not in _TOKEN_STOP:
                start -= 1
            out.append(self._match(start, value_end))
            floor = pos = value_end
        return tuple(out)


# --- url_with_credentials ----------------------------------------------------------------

_SCHEME_SEP: Final = re.compile(r"://")
_SCHEME_CHARS: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-"
)
_ASCII_LETTERS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_SCHEME_MAX: Final = 32
#: Userinfo after ``://``: optional user (may hold a raw ``@``, as in the Azure Database for
#: PostgreSQL single-server ``user@server`` login), ``:``, then the password through the last
#: ``@`` before a ``/`` or whitespace. Unbounded but linear: the user run is possessive and
#: stops at ``:``; the password run stops at ``/`` and whitespace, which end the region, and
#: backtracks at most once over it to the last ``@``.
_USERINFO: Final = re.compile(r"(?P<user>[^\s/:]*+):[^\s/]+@")


class UrlWithCredentialsDetector(_Base):
    """``scheme://user:password@``; the span runs from the scheme through the ``@``."""

    detector_id = "url_with_credentials"
    kinds = frozenset({"url_with_credentials"})
    _category = "url_with_credentials"

    def find(self, text: str) -> tuple[Match, ...]:
        out: list[Match] = []
        floor = 0
        for sep in _SCHEME_SEP.finditer(text):
            if sep.start() < floor:
                continue
            start = sep.start()
            limit = max(floor, start - _SCHEME_MAX)
            while start > limit and text[start - 1] in _SCHEME_CHARS:
                start -= 1
            while start < sep.start() and text[start] not in _ASCII_LETTERS:
                start += 1
            if start >= sep.start():
                continue
            info = _USERINFO.match(text, sep.end())
            if info is None or info.group("user").startswith(_PLACEHOLDER_START):
                continue
            out.append(self._match(start, info.end()))
            floor = info.end()
        return tuple(out)


# --- password_assignment -----------------------------------------------------------------

_KW_PATTERN: Final = (
    r"password|passwd|passphrase|passcode|pwd|\bpin|secret|token"
    r"|api[_-]?key|apikey|access[_-]?key|private[_-]?key"
)
#: A value: a quoted string (backslash escapes and doubled quotes stay inside it, so
#: ``"two \"quoted\" words"`` and ``'it''s'`` are spanned whole; a plain quoted run is the
#: fallback for a trailing backslash) or an unquoted run. Each repeated item is a single
#: character or a fixed two-character pair, so the bounded repetition never nests.
_VALUE_PATTERN: Final = (
    r"\"(?:[^\"\\\r\n]|\\[^\r\n]|\"\"){1,512}\"|'(?:[^'\\\r\n]|\\[^\r\n]|''){1,512}'"
    r"|\"[^\"\r\n]{1,512}\"|'[^'\r\n]{1,512}'|[^\s\"'{\[][^\s\"']{0,511}"
)
#: Credential phrasing. The label is kept, the value spanned. ``suffix`` is a ``_``/``.``/``-``
#: segment or a camelCase word (``tokenValue``); ``max_tokens`` never matches because ``s``
#: is neither. Quantifiers are bounded; the suffix is possessive (no separator character can
#: occur in it, so giving back characters could never let the separator match).
_ASSIGNMENT: Final = re.compile(
    rf"(?i)(?P<kw>{_KW_PATTERN})"
    r"(?P<suffix>[_.-][A-Za-z0-9_.-]{0,40}+|(?-i:[A-Z])[A-Za-z0-9_.-]{0,40}+)?"
    r"(?P<sep>[\"']?(?:[ \t]{0,4}[=:][ \t]{0,4}|[ \t]{1,4}is[ \t]{1,4}))"
    rf"(?P<value>{_VALUE_PATTERN})"
)
_KW: Final = re.compile(rf"(?i){_KW_PATTERN}")
#: A label word (bare or quoted) followed by an assignment operator, matched where a value
#: starts: ``password: client_secret = 'v'`` names a second label, not the value.
_CHAIN_LABEL: Final = re.compile(
    r"(?:\"(?P<dq>[A-Za-z0-9_.-]{1,64}+)\"|'(?P<sq>[A-Za-z0-9_.-]{1,64}+)'"
    r"|(?P<bare>[A-Za-z0-9_.-]{1,64}+))[ \t]{0,4}[=:]"
)
_CHAIN_VALUE: Final = re.compile(rf"[ \t]{{0,4}}(?P<value>{_VALUE_PATTERN})")
_CHAIN_MAX_BLANKS: Final = 4
_IS_ALLOWED: Final = frozenset({"password", "passwd", "passphrase", "passcode", "pwd", "pin"})
#: Label words that name metadata about a credential, not the credential (``token_count``).
_NON_SECRET_SUFFIX: Final = frozenset(
    {
        "count",
        "counts",
        "limit",
        "limits",
        "usage",
        "budget",
        "used",
        "total",
        "max",
        "min",
        "type",
        "types",
        "expiry",
        "expires",
        "expiration",
        "ttl",
        "length",
        "len",
        "size",
        "name",
        "names",
        "id",
        "ids",
        "url",
        "uri",
        "endpoint",
        "path",
        "file",
        "version",
        "kind",
        "format",
    }
)
#: ``max_token``, ``prompt_token``: token-accounting labels, never credentials.
_TOKEN_COUNTER_PREFIX: Final = re.compile(
    r"(?:max|min|num|total|prompt|completion|input|output|cached|reasoning|context)[_.-]?$"
)
_LABEL_CHARS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
_SEGMENT_SPLIT: Final = re.compile(r"[_.-]")
_FIRST_WORD: Final = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z0-9]+")
_EMPTY_VALUES: Final = frozenset({"null", "none", "true", "false", "undefined"})
_SHORT_NUMBER: Final = re.compile(r"[0-9]{1,6}")


def _is_metadata_label(text: str, kw_start: int, kw: str, suffix: str | None) -> bool:
    if suffix:
        segment = _SEGMENT_SPLIT.split(suffix.lstrip("_.-"), maxsplit=1)[0]
        word = _FIRST_WORD.match(segment)
        if word is not None and word.group().lower() in _NON_SECRET_SUFFIX:
            return True
    if kw == "token":
        start = kw_start
        limit = max(0, kw_start - 40)
        while start > limit and text[start - 1] in _LABEL_CHARS:
            start -= 1
        if _TOKEN_COUNTER_PREFIX.search(text[start:kw_start].lower()):
            return True
    return False


class PasswordAssignmentDetector(_Base):
    """``password=``, ``pwd:``, ``client_secret:``, ``AppSecret=``, ``api_key=``, ``token=``
    and similar phrasing; ``password is X`` for the password words. Spans the value only.

    Not credentials: labels whose suffix names metadata (``token_count``, ``secret_name``,
    ``token_limit``), token-accounting labels (``max_token``, ``prompt_tokens``), a ``token``
    value of 6 digits or fewer, ``null``/``true``/``false``-style values and placeholders.

    Chained labels (``password: client_secret = 'v'``, any depth) are spanned from the first
    value through the innermost value, so the inner label is replaced too (over-redaction
    accepted over leaking the value). Quoted values keep escaped and doubled quotes inside.
    """

    detector_id = "password_assignment"
    kinds = frozenset({"password_assignment"})
    _category = "password_assignment"
    _confidence = "medium"

    def find(self, text: str) -> tuple[Match, ...]:
        out: list[Match] = []
        pos = 0
        while True:
            m = _ASSIGNMENT.search(text, pos)
            if m is None:
                break
            if self._accepted(text, m):
                end = max(m.end("value"), _chain_end(text, m.start("value")))
                out.append(self._match(m.start("value"), end))
                pos = end
            elif (label := _chain_label(text, m.start("value"))) is not None:
                # The outer label is not a credential, but its "value" is a label: rescan from
                # the first credential label in the chain so it is judged on its own.
                pos = _first_credential_label(text, label)
            else:
                pos = m.end()
        return tuple(out)

    @staticmethod
    def _accepted(text: str, m: re.Match[str]) -> bool:
        kw = m.group("kw").lower()
        if "is" in m.group("sep").lower() and kw not in _IS_ALLOWED:
            return False
        if _is_metadata_label(text, m.start("kw"), kw, m.group("suffix")):
            return False
        value = m.group("value")
        bare = value[1:-1] if value[0] in "\"'" else value
        if bare.startswith(_PLACEHOLDER_START) or bare.lower() in _EMPTY_VALUES:
            return False
        return not (kw == "token" and _SHORT_NUMBER.fullmatch(bare))


def _chain_label(text: str, start: int) -> re.Match[str] | None:
    """A credential label plus ``=``/``:`` starting at ``start`` (a value that is a label)."""
    label = _CHAIN_LABEL.match(text, start)
    if label is None:
        return None
    word = label.group("dq") or label.group("sq") or label.group("bare") or ""
    return label if _KW.search(word) else None


def _next_chain_label(text: str, label: re.Match[str]) -> re.Match[str] | None:
    pos = label.end()
    blanks = pos + _CHAIN_MAX_BLANKS
    while pos < blanks and pos < len(text) and text[pos] in " \t":
        pos += 1
    return _chain_label(text, pos)


def _is_credential_word(word: str) -> bool:
    """The label word names a credential (``client_secret``), not metadata (``token_count``).

    A chain label is preceded by an operator, blank or quote, never a label character, so the
    metadata check sees the word alone and the answer depends on the word only (cacheable per
    call; nothing derived from the text outlives ``find``).
    """
    for kw in _KW.finditer(word):
        suffix = word[kw.end() :]
        if suffix and not (suffix[0] in "_.-" or suffix[0].isupper()):
            continue  # ``max_tokens``: the assignment pattern never matches here
        if not _is_metadata_label(word, kw.start(), kw.group().lower(), suffix or None):
            return True
    return False


def _first_credential_label(text: str, label: re.Match[str]) -> int:
    """Start of the first credential label in the chain that begins with ``label``, else the
    end of the chain's last label (nothing in the chain is a credential label)."""
    seen: dict[str, bool] = {}
    current: re.Match[str] | None = label
    last = label
    while current is not None:
        word = current.group("dq") or current.group("sq") or current.group("bare")
        if word not in seen:
            seen[word] = _is_credential_word(word)
        if seen[word]:
            return current.start()
        last = current
        current = _next_chain_label(text, current)
    return last.end()


def _chain_end(text: str, start: int) -> int:
    """End of a chained assignment whose first value starts at ``start``, else ``start``.

    ``password: client_secret = 'v'`` (any depth, ``a: b: c = v``): while the candidate value
    is a credential label followed by ``=``/``:``, step to the value after that operator, so the
    span covers the innermost value. Each step costs at most the label it moves over (the value
    is matched once, at the end of the chain), so the walk is linear.
    """
    label = _chain_label(text, start)
    if label is None:
        return start
    while (following := _next_chain_label(text, label)) is not None:
        label = following
    value = _CHAIN_VALUE.match(text, label.end())
    return label.end() if value is None else value.end("value")


# --- opaque_secret -----------------------------------------------------------------------

#: A run of 40 or more key-material characters, scanned once per run (lookbehind).
_OPAQUE_RUN: Final = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{40,}")
#: Shannon entropy per character; random base64 of 40 characters scores about 4.7.
_MIN_ENTROPY_BITS: Final = 4.0
#: Mean length of lowercase runs; random base64 is about 1.7, camelCase words and paths 4+.
_MAX_MEAN_LOWER_RUN: Final = 3.0
_LOWER_RUN: Final = re.compile(r"[a-z]+")


def _looks_like_key_material(run: str) -> bool:
    if not (
        any(c.isupper() for c in run)
        and any(c.islower() for c in run)
        and any(c.isdigit() for c in run)
    ):
        return False
    size = len(run)
    entropy = -sum((k / size) * math.log2(k / size) for k in Counter(run).values())
    if entropy < _MIN_ENTROPY_BITS:
        return False
    lowers = [len(r) for r in _LOWER_RUN.findall(run)]
    return sum(lowers) / len(lowers) < _MAX_MEAN_LOWER_RUN


class OpaqueSecretDetector(_Base):
    """Long opaque runs that look like key material (Clarification 9).

    A run of 40 or more ``[A-Za-z0-9+/_=-]`` characters is reported when it contains an
    uppercase letter, a lowercase letter and a digit, its Shannon entropy is at least 4.0 bits
    per character, and its lowercase letters average fewer than 3 per run (so camelCase
    identifiers, paths, slugs, hex digests and repeated characters do not match). Category
    ``other``, confidence ``low``, sensitivity ``credentials``, always replaced.
    """

    detector_id = "opaque_secret"
    kinds = frozenset({"other"})
    _category = "other"
    _confidence = "low"
    _sensitivity = "credentials"

    def find(self, text: str) -> tuple[Match, ...]:
        return tuple(
            self._match(m.start(), m.end())
            for m in _OPAQUE_RUN.finditer(text)
            if _looks_like_key_material(m.group())
        )


def secret_detectors() -> tuple[Detector, ...]:
    """One instance of each credential and secret detector, in a stable order."""
    return (
        PrivateKeyDetector(),
        JwtDetector(),
        BearerTokenDetector(),
        CloudAccessKeyDetector(),
        VendorApiKeyDetector(),
        ConnectionStringDetector(),
        UrlWithCredentialsDetector(),
        PasswordAssignmentDetector(),
        OpaqueSecretDetector(),
    )
