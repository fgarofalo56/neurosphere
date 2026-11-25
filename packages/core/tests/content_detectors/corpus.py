# ruff: noqa: S311 - seeded, reproducible synthetic data, not cryptography
"""Labelled synthetic corpus and quality measurement for PRP-101 (item 6).

``build_corpus(seed, size)`` assembles deterministic text samples. Ground truth is recorded
while the text is assembled (never by running a detector): every positive identifier or
credential is a labelled ``Span``; hard negatives (lookalikes, checksum-invalid numbers,
digests, versions, token-accounting lines) carry no label. Every value is generated at runtime
from the seed; nothing credential-shaped, no card number, IBAN or SSN is a literal here.

``measure(samples)`` runs each detector of the default set on each sample (precision and recall
per detector) and the whole engine (``redact`` with the default configuration) for the
end-to-end check: a labelled credential or card span is redacted when no 6-character fragment
of its secret survives in the output. The quality gate (GD-19) uses the end-to-end recall.

Shared by ``test_corpus_quality.py`` (CI gate) and ``report_quality.py`` (manual runbook
table); neither is imported by product code.
"""

from __future__ import annotations

import base64
import datetime as dt
import ipaddress
import json
import random
import re
import string
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from neurosphere_core.classification import (
    CREDENTIAL_CATEGORIES,
    DetectorSet,
    Redacted,
    RedactionConfig,
    default_detector_set,
    redact,
)

from .synth import CREDENTIAL_GENERATORS, EXPECTED_CATEGORY, NEGATIVE_LOOKALIKES, secret_value

__all__ = [
    "CHAINED_CONTEXT",
    "CONTEXTS",
    "DEFAULT_SEED",
    "DEFAULT_SIZE",
    "GATED_CATEGORIES",
    "NEGATIVE_KINDS",
    "POSITIVE_KINDS",
    "DetectorQuality",
    "EndToEnd",
    "QualityReport",
    "Sample",
    "Span",
    "build_corpus",
    "measure",
    "render_markdown",
]

DEFAULT_SEED: Final = 20261124

#: GD-19 (Clarification 6): only these reach recall 1.0 on the corpus, end to end.
GATED_CATEGORIES: Final[frozenset[str]] = CREDENTIAL_CATEGORIES | {"payment_card"}
#: Categories a credential match may overlap and still be a true positive (Clarification 9:
#: ``opaque_secret`` reports ``other``).
_SECRET_LIKE: Final[frozenset[str]] = CREDENTIAL_CATEGORIES | {"other"}
_FRAGMENT: Final = 6

#: Context whose credential is expected to leak until the chained-label fix lands.
CHAINED_CONTEXT: Final = "chained_label"

_HEX = "0123456789abcdef"
_ALNUM = string.ascii_letters + string.digits
_GUID_SHAPE: Final = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")


# --- model -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Span:
    """A labelled span: ``text[start:end]`` is one ``category`` value of generator ``kind``.

    ``secret`` is the ``(start, end)`` range that must not survive redaction (the label of a
    labelled kind such as ``password=`` or ``Bearer`` is outside it, as in ``secret_value``).
    """

    start: int
    end: int
    category: str
    kind: str
    secret: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Sample:
    text: str
    spans: tuple[Span, ...]
    kind: str
    context: str

    @property
    def negative(self) -> bool:
        return self.kind in NEGATIVE_KINDS


@dataclass(frozen=True, slots=True)
class _Label:
    start: int
    end: int
    category: str
    kind: str
    secret: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Item:
    text: str
    labels: tuple[_Label, ...] = ()


def _whole(text: str, category: str, kind: str, secret: str | None = None) -> _Item:
    value = text if secret is None else secret
    at = text.find(value)
    if at < 0:
        raise AssertionError("secret not inside item")
    return _Item(text, (_Label(0, len(text), category, kind, (at, at + len(value))),))


# --- helpers ---------------------------------------------------------------------------------


def _run(rng: random.Random, alphabet: str, size: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(size))


def _digits(rng: random.Random, size: int) -> str:
    return _run(rng, string.digits, size)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _luhn_complete(body: str) -> str:
    for check in string.digits:
        if _luhn_ok(body + check):
            return body + check
    raise AssertionError("unreachable")


def _group(digits: str, sizes: Iterable[int], sep: str) -> str:
    out: list[str] = []
    at = 0
    for size in sizes:
        out.append(digits[at : at + size])
        at += size
    if at < len(digits):
        out.append(digits[at:])
    return sep.join(p for p in out if p)


# --- positive generators: payment cards ------------------------------------------------------

#: Major-brand-like prefixes and lengths (brand IIN ranges, synthetic numbers only).
_CARD_BRANDS: Final[tuple[tuple[Callable[[random.Random], str], tuple[int, ...]], ...]] = (
    (lambda r: "4", (13, 16, 19)),
    (lambda r: str(r.randint(51, 55)), (16,)),
    (lambda r: str(r.randint(2221, 2720)), (16,)),
    (lambda r: r.choice(["34", "37"]), (15,)),
    (lambda r: r.choice(["6011", "65"]), (16, 17, 18, 19)),
    (lambda r: "35", (16, 17, 18, 19)),
    (lambda r: r.choice(["36", "38"]), (14,)),
    (lambda r: "62", (16, 17, 18, 19)),
)


def _card_digits(rng: random.Random) -> str:
    prefix_of, lengths = rng.choice(_CARD_BRANDS)
    prefix = prefix_of(rng)
    length = rng.choice(lengths)
    return _luhn_complete(prefix + _digits(rng, length - len(prefix) - 1))


def _format_card(rng: random.Random, digits: str) -> str:
    style = rng.randrange(4)
    if style == 0:
        return digits
    sep = rng.choice([" ", "-"])
    if style == 1 and len(digits) in (14, 15):  # Amex 4-6-5, Diners 4-6-4
        return _group(digits, (4, 6), sep)
    return _group(digits, (4,) * 5, sep)


def _payment_card(rng: random.Random) -> _Item:
    return _whole(_format_card(rng, _card_digits(rng)), "payment_card", "payment_card")


def _luhn_invalid_card(rng: random.Random) -> _Item:
    digits = _card_digits(rng)
    broken = digits[:-1] + str((int(digits[-1]) + 1) % 10)
    return _Item(_format_card(rng, broken))


# --- positive generators: other identifiers --------------------------------------------------

#: (country, total length, leading BBAN letters): ISO 13616 registry lengths.
_IBAN_FORMATS: Final = (
    ("DE", 22, 0),
    ("GB", 22, 4),
    ("FR", 27, 0),
    ("NL", 18, 4),
    ("ES", 24, 0),
    ("IT", 27, 1),
    ("NO", 15, 0),
    ("BE", 16, 0),
    ("CH", 21, 0),
    ("MT", 31, 4),
)


def _iban_compact(rng: random.Random) -> str:
    country, length, letters = rng.choice(_IBAN_FORMATS)
    bban = _run(rng, string.ascii_uppercase, letters) + _digits(rng, length - 4 - letters)
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{country}{98 - int(numeric) % 97:02d}{bban}"


def _format_iban(rng: random.Random, compact: str) -> str:
    if rng.random() < 0.5:
        return compact
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def _iban(rng: random.Random) -> _Item:
    return _whole(_format_iban(rng, _iban_compact(rng)), "iban", "iban")


def _invalid_iban(rng: random.Random) -> _Item:
    compact = _iban_compact(rng)
    broken = f"{compact[:2]}{(int(compact[2:4]) + 1) % 100:02d}{compact[4:]}"
    return _Item(_format_iban(rng, broken))


def _ssn_parts(area: int, group: int, serial: int, sep: str) -> str:
    return f"{area:03d}{sep}{group:02d}{sep}{serial:04d}"


def _us_ssn(rng: random.Random) -> _Item:
    area = rng.choice([a for a in range(1, 900) if a != 666])
    text = _ssn_parts(area, rng.randint(1, 99), rng.randint(1, 9999), rng.choice(["-", " "]))
    return _whole(text, "us_ssn", "us_ssn")


def _excluded_ssn(rng: random.Random) -> _Item:
    area, group, serial = rng.randint(1, 899), rng.randint(1, 99), rng.randint(1, 9999)
    which = rng.randrange(5)
    if which == 0:
        area = 0
    elif which == 1:
        area = 666
    elif which == 2:
        area = rng.randint(900, 999)
    elif which == 3:
        group = 0
    else:
        serial = 0
    return _Item(_ssn_parts(area, group, serial, rng.choice(["-", " "])))


def _email(rng: random.Random) -> _Item:
    local = _run(rng, string.ascii_lowercase, rng.randint(2, 10))
    if rng.random() < 0.5:
        local += rng.choice([".", "_", "+"]) + _run(rng, string.ascii_lowercase, rng.randint(2, 6))
    domain = _run(rng, string.ascii_lowercase, rng.randint(3, 10))
    if rng.random() < 0.3:
        domain = _run(rng, string.ascii_lowercase, rng.randint(2, 6)) + "." + domain
    tld = rng.choice(["com", "org", "net", "io", "example", "co.uk"])
    return _whole(f"{local}@{domain}.{tld}", "email_address", "email_address")


def _phone_e164(rng: random.Random) -> _Item:
    country = rng.choice(["1", "44", "49", "33", "61", "81"])
    text = "+" + country + _digits(rng, rng.randint(9, 15 - len(country)))
    return _whole(text, "phone_number", "phone_e164")


def _phone_national(rng: random.Random) -> _Item:
    area, mid, last = _digits(rng, 3), _digits(rng, 3), _digits(rng, 4)
    text = rng.choice(
        [
            f"({area}) {mid}-{last}",
            f"{area}-{mid}-{last}",
            f"{area}.{mid}.{last}",
            f"{area} {mid} {last}",
            f"+1 {area} {mid} {last}",
            f"+1-{area}-{mid}-{last}",
            f"+44 {_digits(rng, 2)} {_digits(rng, 4)} {last}",
        ]
    )
    return _whole(text, "phone_number", "phone_national")


def _ipv4_text(rng: random.Random) -> str:
    return str(ipaddress.IPv4Address(rng.getrandbits(32)))


def _ipv4(rng: random.Random) -> _Item:
    return _whole(_ipv4_text(rng), "ip_address", "ipv4")


def _ipv6(rng: random.Random) -> _Item:
    style = rng.randrange(4)
    if style == 0:
        text = str(ipaddress.IPv6Address(rng.getrandbits(128)))
    elif style == 1:
        text = ipaddress.IPv6Address(rng.getrandbits(128)).exploded
    elif style == 2:
        text = str(ipaddress.IPv6Address(f"2001:db8::{rng.getrandbits(16):x}"))
    else:
        text = "::ffff:" + _ipv4_text(rng)
    return _whole(text, "ip_address", "ipv6")


def _mac(rng: random.Random) -> _Item:
    pairs = [_run(rng, _HEX, 2) for _ in range(6)]
    style = rng.randrange(3)
    if style == 2:  # Cisco dotted form; at least one hex letter (all-digit form is a limit)
        pairs[0] = rng.choice("abcdef") + pairs[0][1]
        text = ".".join("".join(pairs[i : i + 2]) for i in range(0, 6, 2))
    else:
        text = (":" if style == 0 else "-").join(pairs)
    return _whole(text.upper() if rng.random() < 0.5 else text, "mac_address", "mac_address")


def _guid_text(rng: random.Random) -> str:
    text = "-".join(_run(rng, _HEX, n) for n in (8, 4, 4, 4, 12))
    return text.upper() if rng.random() < 0.3 else text


def _guid(rng: random.Random) -> _Item:
    text = _guid_text(rng)
    if rng.random() < 0.3:  # braces are never part of the span
        return _Item("{" + text + "}", (_Label(1, 1 + len(text), "guid", "guid", (1, 37)),))
    return _whole(text, "guid", "guid")


def _azure_resource_id(rng: random.Random) -> _Item:
    guid = _guid_text(rng)
    head = "/subscriptions/"
    name = _run(rng, string.ascii_lowercase, rng.randint(4, 12))
    provider = rng.choice(
        [
            "Microsoft.Storage/storageAccounts/st",
            "Microsoft.CognitiveServices/accounts/aoai-",
            "Microsoft.KeyVault/vaults/kv-",
        ]
    )
    text = f"{head}{guid}/resourceGroups/rg-{name}/providers/{provider}{name}"
    start = len(head)
    span = (start, start + len(guid))
    return _Item(text, (_Label(*span, "guid", "azure_resource_id", span),))


def _credential(kind: str) -> Callable[[random.Random], _Item]:
    def build(rng: random.Random) -> _Item:
        text = CREDENTIAL_GENERATORS[kind](rng)
        return _whole(text, EXPECTED_CATEGORY[kind], kind, secret_value(kind, text))

    return build


# --- negative generators (label nothing, except a GUID inside a lookalike) -------------------


def _date(rng: random.Random) -> _Item:
    day = dt.date(2020, 1, 1) + dt.timedelta(days=rng.randint(0, 3000))
    return _Item(
        rng.choice(
            [
                day.isoformat(),
                day.strftime("%m/%d/%Y"),
                day.strftime("%d.%m.%Y"),
                day.strftime("%b %d, %Y"),
                day.isoformat() + f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
            ]
        )
    )


def _time(rng: random.Random) -> _Item:
    h, m, s = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
    return _Item(rng.choice([f"{h:02d}:{m:02d}:{s:02d}", f"{h:02d}:{m:02d}", f"{h}:{m:02d} PM"]))


def _version(rng: random.Random) -> _Item:
    a, b, c = rng.randint(0, 20), rng.randint(0, 40), rng.randint(0, 300)
    return _Item(rng.choice([f"{a}.{b}.{c}", f"v{a}.{b}.{c}-rc.{rng.randint(1, 9)}", f"{a}.{b}"]))


def _four_part_version(rng: random.Random) -> _Item:
    """Declared limit: a 4-part version is a valid IPv4 address (reported by ip_address)."""
    return _Item(".".join(str(rng.randint(0, 30)) for _ in range(4)))


def _order_number(rng: random.Random) -> _Item:
    return _Item(
        rng.choice(
            [
                f"ORD-{rng.randint(100000, 999999)}",
                f"PO {rng.randint(1000, 9999)}-{rng.randint(100, 999)}",
                f"#{rng.randint(10_000_000, 99_999_999)}",
                f"INV-{rng.randint(2020, 2026)}-{rng.randint(1, 99999):05d}",
                f"case {rng.randint(100, 999)}/{rng.randint(10000, 99999)}",
            ]
        )
    )


def _git_sha(rng: random.Random) -> _Item:
    return _Item(_run(rng, _HEX, rng.choice([7, 12, 40])))


def _sha256_hex(rng: random.Random) -> _Item:
    return _Item(_run(rng, _HEX, 64))


def _base64_id(rng: random.Random) -> _Item:
    """Short url-safe ids (16-24 characters): below the 40-character opaque threshold."""
    return _Item(base64.urlsafe_b64encode(rng.randbytes(rng.randint(12, 18))).decode().rstrip("="))


def _base64_blob(rng: random.Random) -> _Item:
    """Long base64 payloads: an opaque_secret false-positive class (over-redaction)."""
    return _Item(base64.b64encode(rng.randbytes(rng.randint(32, 60))).decode())


def _data_uri(rng: random.Random) -> _Item:
    mime = rng.choice(["image/png", "image/gif", "application/pdf"])
    return _Item(f"data:{mime};base64," + base64.b64encode(rng.randbytes(60)).decode())


def _sri_hash(rng: random.Random) -> _Item:
    algo, size = rng.choice([("sha256", 32), ("sha384", 48), ("sha512", 64)])
    return _Item(f"{algo}-" + base64.b64encode(rng.randbytes(size)).decode())


def _file_path(rng: random.Random) -> _Item:
    parts = [_run(rng, string.ascii_lowercase, rng.randint(3, 10)) for _ in range(6)]
    stamp = f"{rng.randint(2020, 2026)}/{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}"
    leaf = f"part-{rng.randint(0, 99999):05d}." + rng.choice(["parquet", "json", "log"])
    if rng.random() < 0.5:
        return _Item("/var/lib/" + "/".join(parts[:3]) + f"/{stamp}/" + "/".join(parts[3:]) + leaf)
    return _Item("D:\\data\\" + "\\".join(parts) + "\\" + leaf)


def _lookalike(rng: random.Random) -> _Item:
    text = rng.choice(NEGATIVE_LOOKALIKES(rng))
    if _GUID_SHAPE.fullmatch(text):  # a GUID is a GUID: label it, it is not a credential
        return _whole(text, "guid", "guid")
    return _Item(text)


def _token_usage(rng: random.Random) -> _Item:
    p, c, k = rng.randint(1, 4000), rng.randint(1, 2000), rng.randint(1, 500)
    style = rng.randrange(3)
    if style == 0:
        usage = {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}
        body = {"model": "gpt-4o", "usage": usage, "max_tokens": 4096, "token_count": k}
        return _Item(json.dumps(body))
    if style == 1:
        return _Item(f"max_tokens: 4096\nprompt_tokens: {p}\ncompletion_tokens: {c}\n")
    return _Item(
        f"llm.call prompt_tokens={p} completion_tokens={c} max_tokens=8192 token_count={k}"
    )


def _python_slices(rng: random.Random) -> _Item:
    n = rng.randint(2, 9)
    return _Item(
        f"evens = values[0::{n}]\ntail = rows[start::step]\nx[a::b] = y\nhead = items[:{n}]\n"
    )


_POSITIVE: Final[Mapping[str, Callable[[random.Random], _Item]]] = MappingProxyType(
    {
        **{kind: _credential(kind) for kind in CREDENTIAL_GENERATORS},
        "payment_card": _payment_card,
        "iban": _iban,
        "us_ssn": _us_ssn,
        "email_address": _email,
        "phone_e164": _phone_e164,
        "phone_national": _phone_national,
        "ipv4": _ipv4,
        "ipv6": _ipv6,
        "mac_address": _mac,
        "guid": _guid,
        "azure_resource_id": _azure_resource_id,
    }
)

_NEGATIVE: Final[Mapping[str, Callable[[random.Random], _Item]]] = MappingProxyType(
    {
        "synth_lookalike": _lookalike,
        "luhn_invalid_card": _luhn_invalid_card,
        "invalid_iban": _invalid_iban,
        "excluded_ssn": _excluded_ssn,
        "date": _date,
        "time": _time,
        "version": _version,
        "four_part_version": _four_part_version,
        "order_number": _order_number,
        "git_sha": _git_sha,
        "sha256_hex": _sha256_hex,
        "base64_id": _base64_id,
        "base64_blob": _base64_blob,
        "data_uri": _data_uri,
        "sri_hash": _sri_hash,
        "file_path": _file_path,
        "token_usage": _token_usage,
        "python_slices": _python_slices,
    }
)

POSITIVE_KINDS: Final[tuple[str, ...]] = tuple(_POSITIVE)
NEGATIVE_KINDS: Final[frozenset[str]] = frozenset(_NEGATIVE)
_KINDS: Final[tuple[str, ...]] = (*_POSITIVE, *_NEGATIVE)
#: Identifier generators used as extra items in a mixed row.
_EXTRA_KINDS: Final = ("payment_card", "iban", "us_ssn", "email_address", "ipv4", "guid")


# --- contexts --------------------------------------------------------------------------------


def _json_escape(char: str) -> str:
    return json.dumps(char)[1:-1]


def _py_escape(char: str) -> str:
    return {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(char, char)


class _Builder:
    """Appends text and items, translating item labels to sample offsets."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._size = 0
        self.spans: list[Span] = []

    def raw(self, text: str) -> None:
        self._parts.append(text)
        self._size += len(text)

    def item(self, item: _Item, escape: Callable[[str], str] | None = None) -> None:
        if escape is None:
            rendered = item.text
            pos = list(range(len(item.text) + 1))
        else:
            pieces: list[str] = []
            pos = [0]
            for char in item.text:
                pieces.append(escape(char))
                pos.append(pos[-1] + len(pieces[-1]))
            rendered = "".join(pieces)
        base = self._size
        for label in item.labels:
            self.spans.append(
                Span(
                    start=base + pos[label.start],
                    end=base + pos[label.end],
                    category=label.category,
                    kind=label.kind,
                    secret=(base + pos[label.secret[0]], base + pos[label.secret[1]]),
                )
            )
        self.raw(rendered)

    def text(self) -> str:
        return "".join(self._parts)


_Context = Callable[[_Builder, _Item, random.Random], None]

_SENTENCES: Final = (
    ("Please use ", " for the nightly job and report back."),
    ("The operator pasted ", " into the ticket before the review."),
    ("We saw ", " in yesterday's export; check it again."),
)
_WRAPS: Final = (("(", ")"), ("[", "]"), ("'", "',"), ('"', '";'), ("<", ">"))


def _prose(b: _Builder, item: _Item, rng: random.Random) -> None:
    before, after = rng.choice(_SENTENCES)
    b.raw(before)
    b.item(item)
    b.raw(after)


def _prose_start(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.item(item)
    b.raw(rng.choice([" was rotated during the maintenance window.", "\nend of note"]))


def _prose_end(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw(rng.choice(["Rotate the following before Friday: ", "From the runbook:\n"]))
    b.item(item)


def _punctuation(b: _Builder, item: _Item, rng: random.Random) -> None:
    left, right = rng.choice(_WRAPS)
    b.raw("Value seen " + left)
    b.item(item)
    b.raw(right + " then the job stopped.")


def _json_context(b: _Builder, item: _Item, rng: random.Random) -> None:
    if rng.random() < 0.5:
        b.raw(f'{{"id": {rng.randint(1, 9999)}, "note": "')
        b.item(item, _json_escape)
        b.raw('", "ok": true}')
    else:
        b.raw('{\n  "job": "nightly",\n  "note": "')
        b.item(item, _json_escape)
        b.raw('",\n  "retries": 3\n}\n')


def _yaml(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw("job:\n  name: nightly\n  note: ")
    b.item(item)
    b.raw(f"\n  retries: {rng.randint(1, 5)}\n")


def _env(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw("APP_MODE=batch\nNOTE=")
    b.item(item)
    b.raw(f"\nRETRIES={rng.randint(1, 5)}\n")


def _http_headers(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw(f"POST /v1/jobs/{rng.randint(1, 999)} HTTP/1.1\r\nHost: jobs.example.com\r\nX-Note: ")
    b.item(item)
    b.raw("\r\nContent-Type: application/json\r\n\r\n")


def _log_line(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw(f"2026-11-24T10:{rng.randint(0, 59):02d}:07Z INFO worker[3] job=nightly note=")
    b.item(item)
    b.raw(f" elapsed_ms={rng.randint(1, 900)}")


def _code(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw("client = make_client(\n    region='eastus',\n    note='")
    b.item(item, _py_escape)
    b.raw(f"',\n    retries={rng.randint(1, 5)},\n)\n")


def _markdown_table(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.raw("| field | value |\n| --- | --- |\n| note | ")
    b.item(item)
    b.raw(f" |\n| retries | {rng.randint(1, 5)} |\n")


def _bare(b: _Builder, item: _Item, rng: random.Random) -> None:
    b.item(item)


def _mixed_row(b: _Builder, item: _Item, rng: random.Random) -> None:
    extras = [_POSITIVE[kind](rng) for kind in rng.sample(_EXTRA_KINDS, 2)]
    cells = [item, *extras]
    rng.shuffle(cells)
    b.raw("| ")
    for index, cell in enumerate(cells):
        if index:
            b.raw(" | ")
        b.item(cell)
    b.raw(" |\n")


def _chained_label(b: _Builder, item: _Item, rng: random.Random) -> None:
    """``password: client_secret = '<v>'``: the known in-flight leak (see the strict xfail)."""
    b.raw("password: ")
    b.item(item)


CONTEXTS: Final[Mapping[str, _Context]] = MappingProxyType(
    {
        "prose": _prose,
        "prose_start": _prose_start,
        "prose_end": _prose_end,
        "punctuation": _punctuation,
        "json": _json_context,
        "yaml": _yaml,
        "env": _env,
        "http_headers": _http_headers,
        "log_line": _log_line,
        "code": _code,
        "markdown_table": _markdown_table,
        "bare": _bare,
        "mixed_row": _mixed_row,
    }
)
_CONTEXT_NAMES: Final = tuple(CONTEXTS)
_CHAINED_KINDS: Final = ("password_assignment", "client_secret_assignment")
#: Two full rounds of every kind through every context (see ``build_corpus``).
DEFAULT_SIZE: Final = 2 * len(_KINDS) * len(_CONTEXT_NAMES)


def build_corpus(seed: int = DEFAULT_SEED, size: int = DEFAULT_SIZE) -> list[Sample]:
    """``size`` labelled samples, reproducible from ``seed``.

    Sample ``i`` uses kind ``i % K`` in context ``(i // K + kind index) % C``: every kind goes
    through every context once per ``K * C`` samples. Values and template choices come from
    one ``random.Random(seed)``. Every fourth round, the password kinds go through the chained
    label context instead.
    """
    rng = random.Random(seed)
    samples: list[Sample] = []
    for i in range(size):
        k = i % len(_KINDS)
        rounds = i // len(_KINDS)
        kind = _KINDS[k]
        context = _CONTEXT_NAMES[(rounds + k) % len(_CONTEXT_NAMES)]
        item = (_POSITIVE.get(kind) or _NEGATIVE[kind])(rng)
        builder = _Builder()
        if kind in _CHAINED_KINDS and rounds % 4 == 3:
            context = CHAINED_CONTEXT
            _chained_label(builder, item, rng)
        else:
            CONTEXTS[context](builder, item, rng)
        samples.append(Sample(builder.text(), tuple(builder.spans), kind, context))
    return samples


# --- measurement -----------------------------------------------------------------------------


def _compatible(match_category: str, label_category: str) -> bool:
    if match_category == label_category:
        return True
    return match_category in _SECRET_LIKE and label_category in _SECRET_LIKE


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


@dataclass(frozen=True, slots=True)
class DetectorQuality:
    detector_id: str
    category: str
    support: int
    covered: int
    matches: int
    true_positives: int
    negative_sample_matches: int

    @property
    def precision(self) -> float | None:
        return self.true_positives / self.matches if self.matches else None

    @property
    def recall(self) -> float | None:
        return self.covered / self.support if self.support else None


@dataclass(frozen=True, slots=True)
class EndToEnd:
    """One labelled span through ``redact``: ``leaked`` when a secret fragment survived."""

    category: str
    kind: str
    context: str
    leaked: bool
    failed: str | None


@dataclass(frozen=True, slots=True)
class QualityReport:
    set_version: str
    digest: str
    seed: int
    size: int
    detectors: tuple[DetectorQuality, ...]
    end_to_end: tuple[EndToEnd, ...]
    #: opaque_secret matches on negative samples, by negative kind.
    opaque_negative_fp: Mapping[str, int] = field(default_factory=dict)

    def e2e_recall(
        self, category: str, *, exclude_contexts: frozenset[str] = frozenset()
    ) -> tuple[int, int]:
        """(redacted, support) for ``category``."""
        rows = [
            e
            for e in self.end_to_end
            if e.category == category and e.context not in exclude_contexts
        ]
        return sum(not e.leaked and e.failed is None for e in rows), len(rows)


def _leaked(sample: Sample, span: Span, output: str) -> bool:
    secret = sample.text[span.secret[0] : span.secret[1]]
    outside = sample.text[: span.start] + "\x00" + sample.text[span.end :]
    size = min(_FRAGMENT, len(secret))
    for i in range(len(secret) - size + 1):
        fragment = secret[i : i + size]
        if fragment in output and fragment not in outside:
            return True
    return False


def measure(
    samples: list[Sample],
    *,
    seed: int = DEFAULT_SEED,
    detector_set: DetectorSet | None = None,
    config: RedactionConfig | None = None,
) -> QualityReport:
    """Per-detector precision/recall and per-span end-to-end redaction through ``redact``."""
    dset = detector_set if detector_set is not None else default_detector_set()
    cfg = config if config is not None else RedactionConfig()
    detectors = dset.all_detectors
    support = dict.fromkeys(range(len(detectors)), 0)
    covered = dict.fromkeys(range(len(detectors)), 0)
    matches = dict.fromkeys(range(len(detectors)), 0)
    true_pos = dict.fromkeys(range(len(detectors)), 0)
    on_negative = dict.fromkeys(range(len(detectors)), 0)
    opaque_fp: dict[str, int] = {}
    e2e: list[EndToEnd] = []
    for sample in samples:
        for index, detector in enumerate(detectors):
            found = detector.find(sample.text)
            relevant = [s for s in sample.spans if s.category in detector.kinds]
            support[index] += len(relevant)
            covered[index] += sum(
                any(_overlaps(m.start, m.end, s.start, s.end) for m in found) for s in relevant
            )
            for m in found:
                matches[index] += 1
                hit = any(
                    _overlaps(m.start, m.end, s.start, s.end)
                    and _compatible(m.category, s.category)
                    for s in sample.spans
                )
                true_pos[index] += hit
                if not hit and sample.negative:
                    on_negative[index] += 1
                    if detector.detector_id == "opaque_secret":
                        opaque_fp[sample.kind] = opaque_fp.get(sample.kind, 0) + 1
        result = redact(sample.text, part="prompt", config=cfg, detector_set=dset)
        for span in sample.spans:
            if span.category not in _SECRET_LIKE and span.category != "payment_card":
                continue
            if isinstance(result, Redacted):
                e2e.append(
                    EndToEnd(
                        span.category,
                        span.kind,
                        sample.context,
                        _leaked(sample, span, result.text),
                        None,
                    )
                )
            else:
                e2e.append(EndToEnd(span.category, span.kind, sample.context, False, result.reason))
    rows = tuple(
        DetectorQuality(
            detector_id=d.detector_id,
            category=",".join(sorted(d.kinds)),
            support=support[i],
            covered=covered[i],
            matches=matches[i],
            true_positives=true_pos[i],
            negative_sample_matches=on_negative[i],
        )
        for i, d in enumerate(detectors)
    )
    return QualityReport(
        set_version=dset.version,
        digest=dset.digest,
        seed=seed,
        size=len(samples),
        detectors=rows,
        end_to_end=tuple(e2e),
        opaque_negative_fp=MappingProxyType(dict(sorted(opaque_fp.items()))),
    )


# --- runbook rendering -----------------------------------------------------------------------

TABLE_START: Final = "<!-- quality-table:start -->"
TABLE_END: Final = "<!-- quality-table:end -->"
TABLE_HEADER: Final = "| detector_id | category | support | precision | recall | gated | notes |"

#: (detector_id, note) pairs; a pair, not a ``"id": "note"`` mapping literal, because the
#: pre-commit credential guard reads ``"<...key>": "<text>"`` as an assignment.
_NOTES: Final[Mapping[str, str]] = MappingProxyType(
    dict(
        (
            ("private_key", "PEM blocks, truncated blocks spanned to end of text"),
            ("vendor_api_key", "includes api-key / subscription-key header and query values"),
            ("connection_string", "includes AccountKey=, SharedAccessKey=, SAS sig= and SAS URLs"),
            ("password_assignment", "chained labels leak (strict xfail, item 2 fix lane)"),
            ("opaque_secret", "category other; not gated (Clarification 9); over-redacts base64"),
            ("payment_card", "Luhn-valid only"),
            ("iban", "mod 97 checked"),
            ("us_ssn", "separated forms only"),
            ("phone_number", "low precision by design"),
            ("ip_address", "4-part versions read as IPv4; `a::b` slices read as IPv6"),
            ("guid", "includes GUIDs inside Azure resource IDs"),
        )
    )
)


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_markdown(report: QualityReport, *, today: dt.date) -> str:
    """The generated runbook block (between the markers, markers excluded)."""
    gated_ids = {d.detector_id for d in report.detectors if d.category in GATED_CATEGORIES}
    lines = [
        f"Detector set `{report.set_version}`, digest `{report.digest}`; corpus seed "
        f"`{report.seed}`, {report.size} samples; measured {today.isoformat()} with "
        "`report_quality.py`.",
        "",
        "Per detector (each detector run alone on every sample):",
        "",
        TABLE_HEADER,
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report.detectors:
        gated = "yes" if row.detector_id in gated_ids else "no"
        lines.append(
            f"| `{row.detector_id}` | `{row.category}` | {row.support} | "
            f"{_ratio(row.precision)} | {_ratio(row.recall)} | {gated} | "
            f"{_NOTES.get(row.detector_id, '')} |"
        )
    lines += [
        "",
        "End to end through `redact` with the default configuration (a span counts as redacted "
        "when no 6-character fragment of its secret survives; the gate excludes the "
        f"`{CHAINED_CONTEXT}` context, shown separately):",
        "",
        "| category | support | redacted | recall | gated | chained-label support | "
        "chained-label recall |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    excluded = frozenset({CHAINED_CONTEXT})
    categories = sorted({e.category for e in report.end_to_end})
    for category in categories:
        ok, total = report.e2e_recall(category, exclude_contexts=excluded)
        all_ok, all_total = report.e2e_recall(category)
        c_ok, c_total = all_ok - ok, all_total - total
        gated = "yes" if category in GATED_CATEGORIES else "no"
        lines.append(
            f"| `{category}` | {total} | {ok} | {_ratio(ok / total if total else None)} | "
            f"{gated} | {c_total} | {_ratio(c_ok / c_total if c_total else None)} |"
        )
    fp = report.opaque_negative_fp
    detail = ", ".join(f"`{kind}` {count}" for kind, count in fp.items()) or "none"
    lines += [
        "",
        f"`opaque_secret` matches on hard-negative samples: {sum(fp.values())} ({detail}).",
    ]
    return "\n".join(lines)
