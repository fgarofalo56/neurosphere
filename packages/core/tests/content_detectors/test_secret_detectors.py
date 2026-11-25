# ruff: noqa: S311 - seeded, reproducible synthetic data, not cryptography
"""PRP-101 item 2: credential and secret detectors.

Every credential is generated at runtime (``synth``); nothing credential-shaped is a literal.
The redaction helper below mimics the engine contract (item 5): credential spans first,
longest first, non-overlapping; then the rest; each span becomes ``placeholder(category)``.
"""

from __future__ import annotations

import importlib.util
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import cast

import pytest
from neurosphere_core.classification import (
    ALL_CATEGORIES,
    CREDENTIAL_CATEGORIES,
    Category,
    Detector,
    Match,
    placeholder,
)
from neurosphere_core.classification.detectors.secret_detectors import secret_detectors

from .synth import (
    CREDENTIAL_GENERATORS,
    EXPECTED_CATEGORY,
    NEGATIVE_LOOKALIKES,
    assignment_value,
    secret_value,
)

_PATH = Path(__file__).resolve().parents[4] / "tests" / "contracts" / "validators.py"
_SPEC = importlib.util.spec_from_file_location("ns_contract_validators_prp101_item2", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
sys.path.insert(0, str(_PATH.parent))  # validators imports its sibling contract_support
try:
    _SPEC.loader.exec_module(_MOD)
finally:
    sys.path.remove(str(_PATH.parent))
check_secret_free_text = _MOD.check_secret_free_text
SECRET_TEXT_PATTERNS: dict[str, str] = _MOD.SECRET_TEXT_PATTERNS

DETECTORS: tuple[Detector, ...] = secret_detectors()
BY_ID = {d.detector_id: d for d in DETECTORS}
SEEDS = range(40)
CONTEXTS = (
    "{}",
    "see {} now",
    '{{"value": "{}", "n": 1}}',
    "line one\n{}\nline three",
)
#: Category -> detector id: each credential detector is named after its category.
_EXPECTED_DETECTOR = {c: c for c in CREDENTIAL_CATEGORIES} | {"other": "opaque_secret"}


def _all_matches(text: str) -> list[Match]:
    return [m for d in DETECTORS for m in d.find(text)]


def _select(matches: list[Match]) -> list[Match]:
    def rank(m: Match) -> tuple[int, int, int]:
        return (0 if m.category in CREDENTIAL_CATEGORIES else 1, m.start - m.end, m.start)

    chosen: list[Match] = []
    for m in sorted(matches, key=rank):
        if all(m.end <= c.start or m.start >= c.end for c in chosen):
            chosen.append(m)
    return sorted(chosen, key=lambda m: m.start)


def _redact(text: str) -> str:
    out: list[str] = []
    pos = 0
    for m in _select(_all_matches(text)):
        out.append(text[pos : m.start])
        out.append(placeholder(m.category))
        pos = m.end
    out.append(text[pos:])
    return "".join(out)


def _samples() -> list[tuple[str, int, str]]:
    return [
        (kind, seed, gen(random.Random(f"{kind}:{seed}")))
        for kind, gen in sorted(CREDENTIAL_GENERATORS.items())
        for seed in SEEDS
    ]


SAMPLES = _samples()


def _covered(spans: list[Match], start: int, end: int) -> bool:
    return all(any(m.start <= i < m.end for m in spans) for i in range(start, end))


# --- protocol shape ----------------------------------------------------------------------


@pytest.mark.parametrize("detector", DETECTORS, ids=lambda d: d.detector_id)
def test_detector_satisfies_protocol(detector: Detector) -> None:
    assert isinstance(detector, Detector)
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", detector.detector_id)
    assert detector.version == "1.0.0"
    assert detector.always_redact is True
    assert detector.kinds
    assert detector.kinds <= ALL_CATEGORIES


def test_one_detector_per_id_and_category() -> None:
    assert len(BY_ID) == len(DETECTORS) == 9
    assert set(_EXPECTED_DETECTOR.values()) == set(BY_ID)
    for category, detector_id in _EXPECTED_DETECTOR.items():
        assert BY_ID[detector_id].kinds == frozenset({category})
    assert {c for d in DETECTORS for c in d.kinds} == CREDENTIAL_CATEGORIES | {"other"}


def test_confidence_and_sensitivity() -> None:
    rng = random.Random(7)
    for kind, gen in CREDENTIAL_GENERATORS.items():
        category = EXPECTED_CATEGORY[kind]
        detector = BY_ID[_EXPECTED_DETECTOR[category]]
        for m in detector.find(gen(rng)):
            if category == "other":
                assert (m.confidence, m.sensitivity_category) == ("low", "credentials")
            elif category == "password_assignment":
                assert m.confidence == "medium"
            else:
                assert m.confidence == "high"
            assert m.detector_id == detector.detector_id
            assert m.category == category


# --- recall, coverage, placeholder safety, idempotence -----------------------------------


@pytest.mark.parametrize("kind", sorted(CREDENTIAL_GENERATORS))
def test_kind_detected_by_its_own_detector(kind: str) -> None:
    category = EXPECTED_CATEGORY[kind]
    detector = BY_ID[_EXPECTED_DETECTOR[category]]
    for seed in SEEDS:
        credential = CREDENTIAL_GENERATORS[kind](random.Random(f"{kind}:{seed}"))
        secret = secret_value(kind, credential)
        for template in CONTEXTS:
            text = template.format(credential)
            start = text.index(secret)
            found = list(detector.find(text))
            assert found, f"{kind} seed {seed}: not detected"
            assert _covered(found, start, start + len(secret)), f"{kind} seed {seed}"


@pytest.mark.parametrize("kind", sorted(CREDENTIAL_GENERATORS))
def test_redacted_output_is_secret_free_and_idempotent(kind: str) -> None:
    for seed in SEEDS:
        credential = CREDENTIAL_GENERATORS[kind](random.Random(f"{kind}:{seed}"))
        secret = secret_value(kind, credential)
        for template in CONTEXTS:
            text = template.format(credential)
            start = text.index(secret)
            selected = _select(_all_matches(text))
            assert _covered(selected, start, start + len(secret)), f"{kind} seed {seed}"
            redacted = _redact(text)
            assert check_secret_free_text(redacted) == [], f"{kind} seed {seed}"
            fragments = {secret[i : i + 6] for i in range(len(secret) - 5)}
            survivors = [f for f in fragments if f in redacted and f not in template]
            assert not survivors, f"{kind} seed {seed}: a fragment survived"
            assert _all_matches(redacted) == [], f"{kind} seed {seed}: not idempotent"
            assert _redact(redacted) == redacted


def test_credential_kinds_are_covered_by_a_credential_category() -> None:
    for kind, seed, credential in SAMPLES:
        if EXPECTED_CATEGORY[kind] == "other":
            continue
        secret = secret_value(kind, credential)
        start = credential.index(secret)
        spans = [m for m in _all_matches(credential) if m.category in CREDENTIAL_CATEGORIES]
        assert _covered(spans, start, start + len(secret)), f"{kind} seed {seed}"


def test_several_credentials_in_one_text() -> None:
    rng = random.Random(2026)
    kinds = sorted(CREDENTIAL_GENERATORS)
    parts = [CREDENTIAL_GENERATORS[k](rng) for k in kinds]
    text = "\n".join(f"item {i}: {p}" for i, p in enumerate(parts))
    redacted = _redact(text)
    assert check_secret_free_text(redacted) == []
    assert _all_matches(redacted) == []
    for kind, credential in zip(kinds, parts, strict=True):
        assert secret_value(kind, credential) not in redacted


def test_every_validator_pattern_has_a_detected_generator() -> None:
    """Iterates the validator dict, so a new ``secret_free_text`` pattern breaks this test."""
    for name, pattern in SECRET_TEXT_PATTERNS.items():
        hits = [(k, c) for k, _, c in SAMPLES if re.search(pattern, c)]
        assert hits, f"no generator produces a {name}"
        for kind, credential in hits:
            assert check_secret_free_text(_redact(credential)) == [], f"{name} via {kind}"


#: Glue that must not hide a credential from the detectors (``secret_free_text`` has no left
#: boundaries, so neither may the redaction that feeds it).
_ADVERSARIAL_GLUE = ("x", "_", "ri", "di", " " * 20, "token_", '"', "'", "=")
#: ``sk_``/``pk_`` and Slack ``xox`` keep a deliberate left word boundary (``task_``/``desk_``
#: identifiers); the validator has no rule for them, so after a glued letter only the
#: validator half of the parity check applies.
_WORD_BOUNDARY_KINDS = frozenset({"sk_pk_underscore", "slack_xoxb"})


@pytest.mark.parametrize("kind", sorted(CREDENTIAL_GENERATORS))
def test_glued_credentials_redact_to_validator_clean_text(kind: str) -> None:
    for seed in range(8):
        credential = CREDENTIAL_GENERATORS[kind](random.Random(f"glue:{kind}:{seed}"))
        secret = secret_value(kind, credential)
        fragments = {secret[i : i + 6] for i in range(len(secret) - 5)}
        for before in _ADVERSARIAL_GLUE:
            for after in _ADVERSARIAL_GLUE:
                text = before + credential + after
                redacted = _redact(text)
                label = f"{kind} seed {seed} glue {before!r}/{after!r}"
                assert check_secret_free_text(redacted) == [], label
                if kind in _WORD_BOUNDARY_KINDS and before[-1].isalnum():
                    continue
                survivors = [f for f in fragments if f in redacted and f not in before + after]
                assert not survivors, f"{label}: a fragment survived"


def _validator_probes() -> dict[str, list[str]]:
    """Minimal strings each ``secret_free_text`` pattern rejects, built at runtime."""
    a20 = "a" * 20
    return {
        "private key block": ["x" + "-----BEGIN " + "PRIVATE" + " KEY-----"],
        "JWT": [
            "x" + "eyJ" + "aaaa." + "bbbb.",
            "token_" + "eyJ" + "hbGciOi." + "eyJzdWIi." + "c2ln",
            "name.part." + "eyJ" + "hbGc." + "eyJz.",
        ],
        "bearer token": [
            "auth_" + "bearer " + a20,
            "Bear" + "er" + " " * 20 + "abcdefgh",
            "xBEARER" + "\t" + "abc.def~",
        ],
        "AWS access key id": ["x" + "AK" + "IA" + "A" * 16],
        "GitHub token": ["x" + "gh" + "p_" + a20, "x" + "github" + "_pat_" + a20],
        "sk- key": [
            "dis" + "k-" + "encryption-set-configuration",
            "ris" + "k-" + "assessment-for-quarterly-review",
            "s" + "k-" + "abcdefghijklmnopqrstuvwxyzabcd",
        ],
        "Azure storage or Service Bus key assignment": [
            "x" + "Account" + "Key=" + "abcdefgh",
            "x" + "SharedAccess" + "Key=" + "abcdefgh",
        ],
        "SAS signature": ["xsi" + "g=" + "a" * 30, "si" + "g=" + "%2B" * 7],
        "URL with userinfo": [
            "a://" + "u:" + "p@",
            "https://u:" + "p" * 300 + "@h/",
        ],
    }


def test_every_validator_pattern_is_redacted_from_minimal_probes() -> None:
    """Iterates the validator dict, so a new ``secret_free_text`` pattern breaks this test."""
    probes = _validator_probes()
    assert set(probes) == set(SECRET_TEXT_PATTERNS)
    for name, pattern in SECRET_TEXT_PATTERNS.items():
        for probe in probes[name]:
            assert re.search(pattern, probe), f"{name}: probe does not exercise the rule"
            redacted = _redact(probe)
            assert check_secret_free_text(redacted) == [], f"{name}: {len(probe)} chars"
            assert _all_matches(redacted) == [], f"{name}: not idempotent"


def test_sk_dash_lookalike_is_low_confidence() -> None:
    text = "dis" + "k-" + "encryption-set-configuration"
    (m,) = BY_ID["vendor_api_key"].find(text)
    assert (m.start, m.end, m.confidence) == (2, len(text), "low")


def test_jwt_after_a_dotted_name_is_found_whole() -> None:
    jwt = CREDENTIAL_GENERATORS["jwt"](random.Random(11))
    text = "name.part." + jwt
    (m,) = BY_ID["jwt"].find(text)
    assert (m.start, m.end) == (len("name.part."), len(text))


def test_password_in_url_with_at_in_username() -> None:
    credential = CREDENTIAL_GENERATORS["url_with_at_in_username"](random.Random(12))
    host = credential.rsplit("@", 1)[1]
    redacted = _redact(f"dsn {credential} end")
    assert redacted == f"dsn {placeholder('url_with_credentials')}{host} end"


def test_private_key_without_end_spans_to_end_of_text() -> None:
    credential = CREDENTIAL_GENERATORS["private_key_block_truncated"](random.Random(3))
    text = f"intro {credential}\ntrailing words"
    (m,) = BY_ID["private_key"].find(text)
    assert (m.start, m.end) == (len("intro "), len(text))


def test_private_key_blocks_are_spanned_separately() -> None:
    rng = random.Random(4)
    first = CREDENTIAL_GENERATORS["private_key_block"](rng)
    second = CREDENTIAL_GENERATORS["private_key_block"](rng)
    text = f"{first}\nbetween\n{second}"
    found = BY_ID["private_key"].find(text)
    assert len(found) == 2
    assert "between" in _redact(text)


def test_url_span_runs_through_the_at_sign_and_keeps_the_host() -> None:
    credential = CREDENTIAL_GENERATORS["url_with_userinfo"](random.Random(5))
    host = credential.rsplit("@", 1)[1]
    redacted = _redact(f"connect to {credential} today")
    assert redacted.startswith("connect to " + placeholder("url_with_credentials") + host)


def test_labels_are_kept_and_values_spanned() -> None:
    rng = random.Random(6)
    for kind in ("password_assignment", "bearer_token", "azure_openai_api_key_header"):
        credential = CREDENTIAL_GENERATORS[kind](rng)
        secret = secret_value(kind, credential)
        label = credential[: credential.index(secret)].strip(" \"'=:\t")
        assert label and label in _redact(credential)


def test_bare_32_hex_is_not_a_key_but_header_value_is() -> None:
    rng = random.Random(8)
    hex_key = "".join(rng.choice("0123456789abcdef") for _ in range(32))
    assert _all_matches(f"value {hex_key} end") == []
    assert BY_ID["vendor_api_key"].find(f"api-key: {hex_key}")


@pytest.mark.parametrize("seed", range(5))
def test_negative_lookalikes_are_not_detected(seed: int) -> None:
    for text in NEGATIVE_LOOKALIKES(random.Random(seed)):
        found = [(m.detector_id, m.start, m.end) for m in _all_matches(text)]
        assert found == [], f"lookalike #{NEGATIVE_LOOKALIKES(random.Random(seed)).index(text)}"


def _assert_value_gone(text: str, value: str, label: str) -> None:
    redacted = _redact(text)
    assert check_secret_free_text(redacted) == [], label
    fragments = {value[i : i + 6] for i in range(len(value) - 5)}
    survivors = [f for f in fragments if f in redacted and f not in text.replace(value, "")]
    assert not survivors, f"{label}: a fragment survived"
    assert _all_matches(redacted) == [], f"{label}: not idempotent"


_CHAIN_OUTER = ("password", "token", "secret", "api_key")
_CHAIN_INNER = ("password", "client_secret", "api_key", "secret", "pwd")
_CHAIN_OPS = ("=", ":", " = ", ": ")
_CHAIN_QUOTES = ("", "'", '"')


@pytest.mark.parametrize("inner", _CHAIN_INNER)
@pytest.mark.parametrize("outer", _CHAIN_OUTER)
def test_chained_labels_span_the_inner_value(outer: str, inner: str) -> None:
    """``password: client_secret = 'v'``: the outer label must not take the inner label as
    its value and leave the real value behind."""
    for op in _CHAIN_OPS:
        for quote in _CHAIN_QUOTES:
            for seed in range(5):
                value = assignment_value(random.Random(f"chain:{outer}:{inner}:{seed}"))
                text = f"{outer}: {inner}{op}{quote}{value}{quote}"
                label = f"{outer}/{inner}/{op!r}/{quote!r}/{seed}"
                for template in CONTEXTS:
                    _assert_value_gone(template.format(text), value, label)


@pytest.mark.parametrize("depth", [2, 3, 5, 12])
def test_label_chains_of_any_depth_are_spanned(depth: int) -> None:
    labels = (_CHAIN_OUTER + _CHAIN_INNER) * depth
    for seed in range(5):
        rng = random.Random(f"depth:{depth}:{seed}")
        value = assignment_value(rng)
        chain = "".join(f"{rng.choice(labels)}{rng.choice(_CHAIN_OPS)}" for _ in range(depth))
        _assert_value_gone(f"cfg {chain}'{value}' tail", value, f"depth {depth} seed {seed}")
        assert "tail" in _redact(f"cfg {chain}'{value}' tail")


def test_metadata_outer_label_still_lets_the_inner_label_match() -> None:
    value = assignment_value(random.Random(31))
    for outer in ("token_count", "secret_name", "max_tokens"):
        _assert_value_gone(f"{outer}: client_secret = {value}", value, outer)


@pytest.mark.parametrize("quote", ["'", '"'])
def test_quoted_values_are_spanned_whole(quote: str) -> None:
    for seed in range(10):
        rng = random.Random(f"quoted:{quote}:{seed}")
        first, second = assignment_value(rng), assignment_value(rng)
        bodies = {
            "spaces": f"{first} and {second}",
            "escaped": f"{first}\\{quote} {second}",
            "doubled": f"{first}{quote}{quote}s {second}",
        }
        for name, body in bodies.items():
            for label in ("password", "client_secret", "pwd"):
                for op in ("=", ": ", " = "):
                    text = f"{label}{op}{quote}{body}{quote} next"
                    tag = f"{name} {label}{op!r} seed {seed}"
                    _assert_value_gone(text, first, tag)
                    _assert_value_gone(text, second, tag)
                    assert _redact(text).endswith(" next"), tag


_OP_LABELS = (
    "password",
    "Password",
    "db_password",
    "client_secret",
    "api_key",
    "secret",
    "pwd",
    "token",
    "passwd",
)
_OPERATORS = (
    ":=",
    " := ",
    ":= ",
    "=>",
    " => ",
    "->",
    " -> ",
    "<-",
    " <- ",
    " == ",
    "==",
    " === ",
    " != ",
    "=",
    ": ",
)
_LABEL_QUOTES = ("", "'", '"')
_OP_CONTEXTS = (
    "{}",
    "the config says {} today",
    '{{ {}, "n": 1 }}',
    "    if ({}) {{ return; }}",
    "line one\n{}\nline three",
)


@pytest.mark.parametrize("op", _OPERATORS)
@pytest.mark.parametrize("label", _OP_LABELS)
def test_every_operator_spans_the_value(label: str, op: str) -> None:
    """``password := v``, ``'password' => 'v'``, ``password <- v``, ``password == "v"``."""
    for label_quote in _LABEL_QUOTES:
        for value_quote in ("", "'", '"'):
            for seed in range(3):
                value = assignment_value(random.Random(f"op:{label}:{op}:{seed}"), 16, 16)
                text = f"{label_quote}{label}{label_quote}{op}{value_quote}{value}{value_quote}"
                tag = f"{text!r} seed {seed}"
                for template in _OP_CONTEXTS:
                    _assert_value_gone(template.format(text), value, tag)
                    assert label in _redact(template.format(text)), tag


def _json_wrapped(text: str) -> tuple[str, str, str]:
    """``text`` as a JSON string once and twice (JSON inside a tool-call argument string)."""
    once = json.dumps({"arguments": text})
    return once, json.dumps({"arguments": once}), json.dumps(json.dumps({"cfg": text}))


@pytest.mark.parametrize("op", _OPERATORS)
@pytest.mark.parametrize("label", _OP_LABELS)
def test_every_operator_spans_json_escaped_values(label: str, op: str) -> None:
    """``\\"AZURE_CLIENT_SECRET\\": \\"v\\"``: escaped quotes around the label and the value."""
    for label_quote in _LABEL_QUOTES:
        for value_quote in ("", "'", '"'):
            for seed in range(2):
                value = assignment_value(random.Random(f"json:{label}:{op}:{seed}"), 16, 16)
                text = f"{label_quote}{label}{label_quote}{op}{value_quote}{value}{value_quote}"
                for wrapped in _json_wrapped(text):
                    _assert_value_gone(wrapped, value, f"{wrapped!r}")
                    assert label in _redact(wrapped), wrapped


@pytest.mark.parametrize("label", ["AZURE_CLIENT_SECRET", "client_secret", "password", "apiKey"])
def test_tool_call_arguments_with_escaped_json_are_redacted(label: str) -> None:
    for seed in range(10):
        rng = random.Random(f"toolcall:{label}:{seed}")
        value = assignment_value(rng, 12, 39)
        spaced = f"{assignment_value(rng, 8, 8)} {value}"
        for body in ({label: value, "n": 1}, {"env": {label: value}}, {label: spaced}):
            for wrapped in (json.dumps(json.dumps(body)), json.dumps({"a": json.dumps(body)})):
                _assert_value_gone(wrapped, value, f"{wrapped!r}")
                kept = _redact(wrapped).replace(placeholder("password_assignment"), "")
                assert kept.count(label) == wrapped.count(label), wrapped


_BEARER_SEPARATORS = ("\t", "\n", "\r\n", " \t", "\t\t", " ")


@pytest.mark.parametrize("sep", _BEARER_SEPARATORS, ids=repr)
def test_bearer_with_json_escaped_separators(sep: str) -> None:
    for seed in range(20):
        credential = CREDENTIAL_GENERATORS["bearer_token"](random.Random(f"bjson:{sep}:{seed}"))
        token = secret_value("bearer_token", credential)
        word = credential.split(None, 1)[0]
        raw = f"Authorization: {word}{sep}{token}"
        for wrapped in (
            json.dumps(raw),
            json.dumps(json.dumps(raw)),
            json.dumps({"headers": {"Authorization": f"{word}{sep}{token}"}}),
            json.dumps(json.dumps({"headers": {"Authorization": f"{word}{sep}{token}"}})),
        ):
            assert BY_ID["bearer_token"].find(wrapped), wrapped
            _assert_value_gone(wrapped, token, f"{wrapped!r}")
            assert word in _redact(wrapped)


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"token_count": 12, "max_tokens": 4096}),
        json.dumps(json.dumps({"token_count": 12, "secret_name": "storage-primary"})),
        json.dumps(json.dumps({"password": None, "token": "4096"})),
        json.dumps("bearer\tok"),
        json.dumps("the bearer\nof news"),
    ],
)
def test_json_escaped_lookalikes_are_not_detected(text: str) -> None:
    found = [(m.detector_id, m.start, m.end) for m in _all_matches(text)]
    assert found == [], text


@pytest.mark.parametrize("op", _OPERATORS)
def test_chains_work_with_every_operator(op: str) -> None:
    for seed in range(5):
        value = assignment_value(random.Random(f"opchain:{op}:{seed}"), 16, 16)
        for inner in ("client_secret", "api_key", "pwd"):
            text = f"password{op}{inner}{op}{value}"
            _assert_value_gone(f"cfg {text} tail", value, f"{text!r}")
            assert "tail" in _redact(f"cfg {text} tail")


_FLAGS = (
    "--password",
    "--db-password",
    "--client-secret",
    "--api-key",
    "--secret",
    "--token",
    "-Password",
    "-ClientSecret",
)
_FLAG_FORMS = (" {}", "={}", "  {}", " '{}'", ' "{}"', "\t{}")
_FLAG_CONTEXTS = (
    "{}",
    "mytool deploy {} --verbose",
    "Connect-Thing -Server db01 {} -Force",
    "run: |\n  cli login {}\n",
)


@pytest.mark.parametrize("flag", _FLAGS)
def test_cli_flags_span_the_value(flag: str) -> None:
    for form in _FLAG_FORMS:
        for seed in range(5):
            value = assignment_value(random.Random(f"flag:{flag}:{seed}"), 16, 16)
            text = flag + form.format(value)
            for template in _FLAG_CONTEXTS:
                full = template.format(text)
                _assert_value_gone(full, value, f"{full!r}")
                redacted = _redact(full)
                assert flag in redacted, full
                for kept in ("--verbose", "-Server db01", "-Force"):
                    if kept in full:
                        assert kept in redacted, full


@pytest.mark.parametrize(
    "text",
    [
        "--max-tokens 4096",
        "--max-token 4096",
        "--token-count 12",
        "--token 4096",
        "--secret-name storage-primary",
        "--verbose --dry-run",
        "-Server db01 -Force",
        "token_count => 12",
        "prompt_tokens -> 5",
        "max_tokens := 4096",
        "completion_tokens == 345",
        "secret_name => storage-primary",
        "x <- 3",
        "a <- b",
        "step one -> step two",
        "data => result",
        "if count == 3",
        "value != other",
        "password => null",
        "--password true",
        "the well-known secret handshake",
    ],
)
def test_operator_and_flag_lookalikes_are_not_detected(text: str) -> None:
    found = [(m.detector_id, m.start, m.end) for m in _all_matches(text)]
    assert found == [], text


def test_label_arrow_in_prose_is_over_redacted() -> None:
    """Accepted false positive: a credential label then an arrow spans the next word."""
    redacted = _redact("password -> reset flow")
    assert redacted == "password -> " + placeholder("password_assignment") + " flow"


def test_placeholders_trigger_nothing() -> None:
    for category in sorted(ALL_CATEGORIES):
        text = placeholder(cast("Category", category))
        for wrapper in (
            "{}",
            "password={}",
            "Bearer {}",
            "api-key: {}",
            '"secret": "{}"',
            "password => {}",
            "password := '{}'",
            "client_secret <- {}",
            'password == "{}"',
            "--password {}",
            "-ClientSecret '{}'",
        ):
            assert _all_matches(wrapper.format(text)) == []


# --- linear time -------------------------------------------------------------------------

_ONE_MB = 1_000_000


def _rep(fragment: str) -> str:
    return fragment * (_ONE_MB // len(fragment))


_ADVERSARIAL = {
    "a-run": "a" * _ONE_MB,
    "equals-run": "=" * _ONE_MB,
    "eyJ-repeat": "eyJ" * (_ONE_MB // 3),
    "eyJ-dot-repeat": "eyJaaaa." * (_ONE_MB // 8),
    "begin-repeat": "-----BEGIN " * (_ONE_MB // 11),
    "begin-private-unterminated": "-----BEGIN PRIVATE" + " KEY-----" + "A" * _ONE_MB,
    "dash-run": "-" * _ONE_MB,
    "scheme-repeat": "a://" * (_ONE_MB // 4),
    "userinfo-no-at": "x://u:" + "b" * _ONE_MB,
    "colon-repeat": "a:" * (_ONE_MB // 2),
    "password-repeat": _rep("password="),
    "token-dot-repeat": "token." * (_ONE_MB // 6),
    "anchor-repeat": "AccountKey=" * (_ONE_MB // 11),
    "sig-repeat": "sig=" * (_ONE_MB // 4),
    "bearer-repeat": "bearer " * (_ONE_MB // 7),
    "gh-repeat": "ghp_" * (_ONE_MB // 4),
    "sk-repeat": " sk-" * (_ONE_MB // 4),
    "api-key-repeat": _rep("api-key:"),
    "base64-ish": ("Ab1+" * (_ONE_MB // 4)),
    "bearer-long-blank": "bearer" + " " * _ONE_MB + "[",
    "bearer-blank-repeat": _rep("bearer" + " " * 40),
    "sk-long-run": "sk-" + "a" * _ONE_MB,
    "sk-dash-repeat": "sk-" * (_ONE_MB // 3),
    "sk-short-repeat": _rep("sk-" + "a" * 19 + " "),
    "jwt-dot-run": "a." * (_ONE_MB // 2),
    "jwt-segment-repeat": _rep("aaaaaaa."),
    "jwt-head-no-dot": "eyJ" + "a" * _ONE_MB,
    "jwt-short-head-repeat": _rep("eyJaaa.aaaa."),
    "url-colon-at-run": "x://" + "x:x:x@@@" * (_ONE_MB // 8),
    "url-user-no-colon": "x://" + "u@" * (_ONE_MB // 2),
    "url-scheme-colon-repeat": _rep("x://x:x"),
    "xsig-repeat": _rep("xsig="),
    "label-chain-repeat": _rep("password: "),
    "label-chain-tight-repeat": _rep("password:"),
    "metadata-chain-repeat": _rep("token_count: "),
    "metadata-chain-tight-repeat": _rep("token_count:"),
    "mixed-chain-repeat": _rep("token_count: client_secret = "),
    "quoted-chain-repeat": _rep("password: 'secret': "),
    "quote-open-repeat": _rep("pwd" + "='"),
    "escaped-quote-repeat": "pwd" + '="' + '\\"' * (_ONE_MB // 2),
    "doubled-quote-repeat": "pwd" + "='" + "''a" * (_ONE_MB // 3),
    "fat-arrow-chain-repeat": _rep("password => "),
    "fat-arrow-tight-repeat": _rep("password=>"),
    "walrus-chain-repeat": _rep("password := "),
    "thin-arrow-tight-repeat": _rep("password->"),
    "left-arrow-repeat": _rep("a<-"),
    "label-left-arrow-repeat": _rep("pwd<-"),
    "comparison-repeat": _rep("password === "),
    "label-dash-repeat": _rep("db_password-"),
    "flag-repeat": _rep("--password "),
    "flag-tight-repeat": _rep("--password"),
    "flag-other-repeat": _rep("--x y "),
    "flag-quote-open-repeat": _rep('-a "'),
    "flag-dash-run": "--" + "a" * _ONE_MB,
    "escaped-quote-run": "\\" + '"' + "\\" * _ONE_MB,
    "escaped-quote-pair-repeat": _rep("\\" + '"'),
    "escaped-value-open-repeat": _rep("pwd=" + "\\" + '"'),
    "escaped-value-unterminated": "pwd=" + "\\" + '"' + "a" * _ONE_MB,
    "escaped-label-repeat": _rep("\\" + '"' + "password" + "\\" + '": '),
    "escaped-tab-repeat": _rep("\\t"),
    "bearer-escaped-tab-run": "bearer" + "\\t" * (_ONE_MB // 2) + "[",
    "bearer-escaped-tab-repeat": _rep("bearer" + "\\t"),
    "bearer-backslash-run": "bearer" + "\\" * _ONE_MB,
}


@pytest.mark.parametrize("name", sorted(_ADVERSARIAL))
def test_each_detector_is_linear_on_adversarial_input(name: str) -> None:
    text = _ADVERSARIAL[name]
    for detector in DETECTORS:
        started = time.perf_counter()
        detector.find(text)
        elapsed = time.perf_counter() - started
        # Locally the slowest detector takes ~0.7 s per 1 MB input; super-linear backtracking
        # would take minutes. 3 s keeps that signal without flaking on loaded CI runners.
        assert elapsed < 3.0, f"{detector.detector_id} took {elapsed:.2f}s on {name}"
