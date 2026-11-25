"""PRP-101 item 7: ``redact`` never leaks matched text (acceptance criteria 1, 4 and 7).

The corpus is built at runtime: every synthetic credential kind from ``synth.py`` x several
seeds x six carrier contexts (prose, JSON, YAML, env, HTTP header, log line), plus payment
cards, emails and SSNs generated in-test. For every case the suite asserts that no 6+ character
window of the secret survives in the output, in ``repr``/``str``/``model_dump_json`` of the
result or any ``Finding``, or in any log record (all loggers at DEBUG); that no derived form
(sha256/sha1/md5 digests and their 8-char prefixes, base64/base64url, the reversed secret, the
length attached to a placeholder) appears; and that placeholders are exactly
``[[ns-redacted:<category>]]``.

A window is a leak only when it is not explained by text the test itself wrote around the
secret (context template, kept label, placeholders): see ``_values.leaked_fragments``.

Not in the corpus: chained assignment labels (``password: client_secret = '<v>'``) leak today in
the password_assignment detector; a separate PRP-101 lane owns that fix and
``packages/core/tests/content_detectors/test_engine.py`` carries its strict xfail.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, cast

import pytest
from neurosphere_core.classification import (
    ALL_CATEGORIES,
    CREDENTIAL_CATEGORIES,
    PLACEHOLDER_RE,
    Category,
    Redacted,
    RedactionConfig,
    RedactionMode,
    RedactionResult,
    default_detector_set,
    redact,
)

from ._values import (
    ALL_PLACEHOLDERS,
    CREDENTIAL_GENERATORS,
    capture_all_loggers,
    card,
    derived_forms,
    email,
    leaked_fragments,
    length_decorations,
    log_text,
    secret_value,
    ssn,
)

DETECTORS: Final = default_detector_set()
SEEDS: Final = range(3)
CONTEXTS: Final[dict[str, str]] = {
    "prose": "Please use {} for the nightly job and report back.",
    "json": '{{"value": "{}", "n": 1}}',
    "yaml": "settings:\n  note: {}\n  retries: 3\n",
    "env": "export NS_JOB_VALUE={}\nexport NS_JOB_MODE=batch\n",
    "header": "GET /v1/items HTTP/1.1\r\nX-Request-Context: {}\r\nAccept: */*\r\n",
    "log": "2026-11-24T10:00:00Z INFO worker.job id=42 detail={} status=ok",
}

CONFIGS: Final[dict[str, RedactionConfig]] = {
    "default": RedactionConfig(),
    "default_keep": RedactionConfig(default_mode="keep"),
    "non_credential_keep": RedactionConfig(
        modes={
            cast("Category", c): cast("RedactionMode", "keep")
            for c in sorted(ALL_CATEGORIES - CREDENTIAL_CATEGORIES)
        }
    ),
}


@dataclass(frozen=True)
class Case:
    label: str
    text: str
    secret: str
    benign: tuple[str, ...]


def _credential_cases() -> list[Case]:
    cases: list[Case] = []
    for kind in sorted(CREDENTIAL_GENERATORS):
        for seed in SEEDS:
            credential = CREDENTIAL_GENERATORS[kind](random.Random(f"{kind}:{seed}"))
            secret = secret_value(kind, credential)
            label = tuple(part for part in credential.split(secret) if part)
            for name, template in CONTEXTS.items():
                cases.append(
                    Case(
                        label=f"{kind}/seed{seed}/{name}",
                        text=template.format(credential),
                        secret=secret,
                        benign=(*template.split("{}"), *label, *ALL_PLACEHOLDERS),
                    )
                )
    return cases


def _identifier_cases() -> list[Case]:
    cases: list[Case] = []
    for seed in range(8):
        rng = random.Random(f"identifiers:{seed}")
        for kind, value in (("card", card(rng)), ("ssn", ssn(rng)), ("email", email(rng))):
            for name, template in CONTEXTS.items():
                cases.append(
                    Case(
                        label=f"{kind}/seed{seed}/{name}",
                        text=template.format(value),
                        secret=value,
                        benign=(*template.split("{}"), *ALL_PLACEHOLDERS),
                    )
                )
    return cases


CREDENTIAL_CASES: Final = _credential_cases()
IDENTIFIER_CASES: Final = _identifier_cases()


@pytest.fixture
def all_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    for _ in capture_all_loggers(caplog):
        yield caplog


def _surfaces(result: RedactionResult) -> str:
    """Every rendering of ``result`` a caller could log, store or return."""
    parts = [repr(result), str(result), result.model_dump_json()]
    if isinstance(result, Redacted):
        parts.append(result.text)
        for finding in result.findings:
            parts += [repr(finding), str(finding), finding.model_dump_json()]
    return "\n".join(parts)


def _assert_strict_placeholders(output: str, label: str) -> None:
    tokens = PLACEHOLDER_RE.findall(output)
    assert output.count("[[ns-redacted:") == len(tokens), label
    assert set(tokens) <= ALL_CATEGORIES, label
    stripped = PLACEHOLDER_RE.sub("", output)
    assert "ns-redacted" not in stripped, label


def _check(case: Case, result: RedactionResult, logs: str) -> list[str]:
    """Problems found for one case (labels and window counts only, never the secret)."""
    problems: list[str] = []
    surfaces = _surfaces(result)
    haystack = surfaces + "\n" + logs
    if case.secret in haystack:
        problems.append(f"{case.label}: whole secret present")
    windows = leaked_fragments(case.secret, haystack, case.benign)
    if windows:
        problems.append(f"{case.label}: {len(windows)} secret window(s) present")
    rev = leaked_fragments(case.secret[::-1], haystack, case.benign)
    if rev:
        problems.append(f"{case.label}: {len(rev)} reversed-secret window(s) present")
    for form, encoded in derived_forms(case.secret).items():
        if encoded in haystack:
            problems.append(f"{case.label}: derived form {form} present")
    for decorated in length_decorations(case.secret):
        if decorated in haystack:
            problems.append(f"{case.label}: secret length next to a placeholder")
            break
    if logs.strip():
        problems.append(f"{case.label}: classification emitted log records")
    return problems


def _run_corpus(
    cases: list[Case], config: RedactionConfig, caplog: pytest.LogCaptureFixture
) -> tuple[list[str], int]:
    problems: list[str] = []
    replaced = 0
    for case in cases:
        caplog.clear()
        result = redact(case.text, part="prompt", config=config, detector_set=DETECTORS)
        logs = log_text(caplog.records)
        assert isinstance(result, Redacted), f"{case.label}: {result!r}"
        _assert_strict_placeholders(result.text, case.label)
        replaced += any(f.action == "replaced" for f in result.findings)
        problems += _check(case, result, logs)
    return problems, replaced


def test_corpus_covers_every_kind_and_context() -> None:
    kinds = {case.label.split("/")[0] for case in CREDENTIAL_CASES}
    assert kinds == set(CREDENTIAL_GENERATORS)
    assert len(CREDENTIAL_CASES) == len(CREDENTIAL_GENERATORS) * len(SEEDS) * len(CONTEXTS)
    assert all(len(case.secret) >= 8 for case in CREDENTIAL_CASES)


@pytest.mark.parametrize("config_name", sorted(CONFIGS))
def test_credentials_never_leak(all_logs: pytest.LogCaptureFixture, config_name: str) -> None:
    problems, replaced = _run_corpus(CREDENTIAL_CASES, CONFIGS[config_name], all_logs)
    assert not problems, problems
    assert replaced == len(CREDENTIAL_CASES)


def test_identifiers_never_leak_under_default_config(
    all_logs: pytest.LogCaptureFixture,
) -> None:
    problems, replaced = _run_corpus(IDENTIFIER_CASES, CONFIGS["default"], all_logs)
    assert not problems, problems
    assert replaced == len(IDENTIFIER_CASES)


def test_mixed_document_never_leaks(all_logs: pytest.LogCaptureFixture) -> None:
    """Every credential kind plus identifiers in one part: clusters must not merge-leak."""
    rng = random.Random("mixed")
    pieces: list[str] = []
    secrets: list[str] = []
    benign: list[str] = [*ALL_PLACEHOLDERS]
    for index, kind in enumerate(sorted(CREDENTIAL_GENERATORS)):
        credential = CREDENTIAL_GENERATORS[kind](rng)
        secret = secret_value(kind, credential)
        secrets.append(secret)
        benign += [part for part in credential.split(secret) if part]
        template = list(CONTEXTS.values())[index % len(CONTEXTS)]
        benign += template.split("{}")
        pieces.append(template.format(credential))
    for value in (card(rng), ssn(rng), email(rng)):
        secrets.append(value)
        pieces.append(f"Customer reference {value} noted.")
    benign.append("Customer reference ")
    benign.append(" noted.")
    text = "\n\n".join(pieces)
    for config_name, config in CONFIGS.items():
        all_logs.clear()
        result = redact(text, part="tool_output", config=config, detector_set=DETECTORS)
        assert isinstance(result, Redacted), config_name
        _assert_strict_placeholders(result.text, config_name)
        logs = log_text(all_logs.records)
        checked = secrets if config_name == "default" else secrets[: len(CREDENTIAL_GENERATORS)]
        problems: list[str] = []
        for position, secret in enumerate(checked):
            case = Case(f"{config_name}/mixed#{position}", text, secret, tuple(benign))
            problems += _check(case, result, logs)
        assert not problems, problems


def test_leak_oracle_has_teeth() -> None:
    """``_check`` flags each leak shape it claims to flag (guards against a vacuous oracle)."""
    case = next(c for c in CREDENTIAL_CASES if c.label.startswith("github_pat_classic"))
    token = "[[ns-redacted:vendor_api_key]]"
    middle = case.secret[len(case.secret) // 2 : len(case.secret) // 2 + 6]
    forms = derived_forms(case.secret)
    leaky = {
        "window": f"x {token} {middle}",
        "reversed": f"x {token} {case.secret[::-1][3:12]}",
        "sha256_prefix": f"x {token} {forms['sha256_prefix8']}",
        "base64": f"x {token} {forms['base64']}",
        "length": f"x {token}:{len(case.secret)}",
    }
    for shape, text in leaky.items():
        result = Redacted(text=text, findings=(), set_version="item7")
        assert _check(case, result, ""), shape
    clean = Redacted(text=f"x {token} y", findings=(), set_version="item7")
    assert not _check(case, clean, "")
    assert _check(case, clean, "a log line")


def test_placeholders_are_bare_category_tokens() -> None:
    for token in ALL_PLACEHOLDERS:
        match = PLACEHOLDER_RE.fullmatch(token)
        assert match is not None
        assert token == f"[[ns-redacted:{match.group('category')}]]"
