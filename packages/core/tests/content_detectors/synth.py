"""Seeded synthetic credentials for the PRP-101 detector tests (items 2, 5, 6 and 7).

Gitleaks fingerprints commit-scoped strings, so no credential-shaped literal lives in this file:
every key, token and connection string is assembled at runtime from fragments with a
``random.Random`` the caller seeds. Each generator draws lengths and alphabets from within the
documented format (runbook "Sources"), so recall is never measured on one fixed string.

API (keep small and stable):
- ``CREDENTIAL_GENERATORS``: kind -> ``(rng) -> str``; the string is the credential as it would
  appear in text, label included where the format has one (``Bearer``, ``password=``).
- ``EXPECTED_CATEGORY``: kind -> detected category.
- ``secret_value(kind, credential)``: the part that must not survive redaction (the label is
  kept by design for labelled kinds).
- ``NEGATIVE_LOOKALIKES(rng)``: strings that must not be detected as credentials.
"""

from __future__ import annotations

import base64
import json
import random
import string
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import cast
from urllib.parse import quote

from neurosphere_core.classification import placeholder
from neurosphere_core.classification.models import ALL_CATEGORIES, Category

__all__ = [
    "CREDENTIAL_GENERATORS",
    "EXPECTED_CATEGORY",
    "NEGATIVE_LOOKALIKES",
    "secret_value",
]

_UPPER = string.ascii_uppercase
_LOWER = string.ascii_lowercase
_DIGITS = string.digits
_ALNUM = _UPPER + _LOWER + _DIGITS
_B64 = _ALNUM + "+/"
_B64URL = _ALNUM + "-_"
_HEX = "0123456789abcdef"
_DASHES = "-" * 5


def _run(rng: random.Random, alphabet: str, size: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(size))


def _mixed(rng: random.Random, alphabet: str, size: int) -> str:
    """A run over ``alphabet`` that holds at least one uppercase, lowercase and digit."""
    chars = [rng.choice(alphabet) for _ in range(size)]
    slots = rng.sample(range(size), 3)
    for slot, pool in zip(slots, (_UPPER, _LOWER, _DIGITS), strict=True):
        chars[slot] = rng.choice(pool)
    return "".join(chars)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_key(rng: random.Random, raw_bytes: int) -> str:
    return base64.b64encode(rng.randbytes(raw_bytes)).decode("ascii")


def _jwt(rng: random.Random) -> str:
    header = {"alg": rng.choice(["HS256", "RS256", "ES256"]), "typ": "JWT"}
    if rng.random() < 0.5:
        header["kid"] = _run(rng, _ALNUM, rng.randint(6, 20))
    payload = {
        "sub": _run(rng, _ALNUM, rng.randint(6, 24)),
        "iat": rng.randint(1_600_000_000, 1_900_000_000),
        "aud": _run(rng, _LOWER, rng.randint(3, 12)),
    }
    head = _b64url(json.dumps(header, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(rng.randbytes(rng.choice([32, 64, 48])))
    return f"{head}.{body}.{sig}"


def _private_key_header(rng: random.Random) -> tuple[str, str]:
    label = rng.choice(["", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED ", "DSA "])
    middle = f"{label}PRIVATE" + " KEY"
    return f"{_DASHES}BEGIN {middle}{_DASHES}", f"{_DASHES}END {middle}{_DASHES}"


def _private_key_body(rng: random.Random) -> list[str]:
    lines = [_run(rng, _B64, 64) for _ in range(rng.randint(3, 12))]
    lines.append(_run(rng, _B64, rng.randint(8, 60)) + rng.choice(["", "=", "=="]))
    return lines


def _private_key_block(rng: random.Random) -> str:
    begin, end = _private_key_header(rng)
    newline = rng.choice(["\n", "\r\n"])
    return newline.join([begin, *_private_key_body(rng), end])


def _private_key_block_truncated(rng: random.Random) -> str:
    begin, _ = _private_key_header(rng)
    return "\n".join([begin, *_private_key_body(rng)])


def _bearer_token(rng: random.Random) -> str:
    word = rng.choice(["Bearer", "bearer", "BEARER"])
    token = _mixed(rng, _B64URL + ".~+/", rng.randint(20, 80)) + rng.choice(["", "=", "=="])
    return f"{word}{rng.choice([' ', '  ', chr(9)])}{token}"


def _aws_access_key_id(rng: random.Random) -> str:
    return rng.choice(["AK" + "IA", "AS" + "IA"]) + _run(rng, _UPPER + _DIGITS, 16)


def _github_pat_classic(rng: random.Random) -> str:
    return "gh" + "p_" + _mixed(rng, _ALNUM, 36)


def _github_other_token(rng: random.Random) -> str:
    return "gh" + rng.choice("ousr") + "_" + _mixed(rng, _ALNUM, rng.randint(36, 40))


def _github_fine_grained_pat(rng: random.Random) -> str:
    return "github" + "_pat_" + _mixed(rng, _ALNUM, 22) + "_" + _mixed(rng, _ALNUM, 59)


def _github_app_installation_stateless(rng: random.Random) -> str:
    return "gh" + "s_" + _run(rng, _DIGITS, rng.randint(5, 9)) + "_" + _jwt(rng)


def _openai_style_sk(rng: random.Random) -> str:
    return "sk" + "-" + rng.choice(["", "proj-"]) + _mixed(rng, _ALNUM, rng.randint(32, 64))


def _sk_pk_underscore(rng: random.Random) -> str:
    prefix = rng.choice(["sk", "pk"]) + "_" + rng.choice(["", "live_", "test_"])
    return prefix + _mixed(rng, _ALNUM, rng.randint(24, 48))


def _slack_token(rng: random.Random) -> str:
    return (
        "xo"
        + "x"
        + rng.choice("bap")
        + "-"
        + _run(rng, _DIGITS, rng.randint(10, 13))
        + "-"
        + _run(rng, _DIGITS, rng.randint(10, 13))
        + "-"
        + _mixed(rng, _ALNUM, 24)
    )


def _account_name(rng: random.Random) -> str:
    return _run(rng, _LOWER, 1) + _run(rng, _LOWER + _DIGITS, rng.randint(2, 23))


def _storage_suffix(rng: random.Random) -> str:
    return rng.choice(["core.windows.net", "core.usgovcloudapi.net"])


def _storage_account_key(rng: random.Random) -> str:
    return _b64_key(rng, 64)  # 88 characters ending "=="


def _azure_storage_connection_string(rng: random.Random) -> str:
    parts = [
        "DefaultEndpointsProtocol=" + rng.choice(["https", "http"]),
        "AccountName=" + _account_name(rng),
        "Account" + "Key=" + _storage_account_key(rng),
    ]
    if rng.random() < 0.6:
        parts.append("EndpointSuffix=" + _storage_suffix(rng))
    return ";".join(parts)


def _sas_query(rng: random.Random) -> str:
    params = [
        "sv=2022-11-02",
        "ss=" + rng.choice(["b", "bf", "bqtf"]),
        "srt=" + rng.choice(["s", "co", "sco"]),
        "sp=" + rng.choice(["r", "rl", "rwdlac"]),
        f"se=2026-12-{rng.randint(10, 28)}T00:00:00Z",
        "spr=https",
        "si" + "g=" + quote(_b64_key(rng, 32), safe=""),
    ]
    head, sig = params[:-1], params[-1]
    rng.shuffle(head)
    position = rng.randint(0, len(head))
    return "&".join([*head[:position], sig, *head[position:]])


def _azure_storage_sas_connection_string(rng: random.Random) -> str:
    account = _account_name(rng)
    suffix = _storage_suffix(rng)
    endpoints = [
        f"{service}Endpoint=https://{account}.{service.lower()}.{suffix}/"
        for service in rng.sample(["Blob", "Queue", "File", "Table"], rng.randint(1, 4))
    ]
    return ";".join([*endpoints, "SharedAccess" + "Signature=" + _sas_query(rng)])


def _namespace(rng: random.Random) -> str:
    return _run(rng, _LOWER, 1) + _run(rng, _LOWER + _DIGITS + "-", rng.randint(5, 20)) + "x"


def _service_bus_connection_string(rng: random.Random) -> str:
    host = rng.choice(["servicebus.windows.net", "servicebus.usgovcloudapi.net"])
    parts = [
        f"Endpoint=sb://{_namespace(rng)}.{host}/",
        "SharedAccessKeyName=" + rng.choice(["RootManageSharedAccessKey", "send", "listen"]),
        "SharedAccess" + "Key=" + _b64_key(rng, 32),
    ]
    if rng.random() < 0.5:
        parts.append("EntityPath=" + _run(rng, _LOWER, rng.randint(3, 12)))
    return ";".join(parts)


def _account_key_assignment(rng: random.Random) -> str:
    spaces = (" " * rng.randint(0, 2), " " * rng.randint(0, 2))
    return "Account" + "Key" + spaces[0] + "=" + spaces[1] + _storage_account_key(rng)


def _shared_access_key_assignment(rng: random.Random) -> str:
    return "SharedAccess" + "Key=" + _b64_key(rng, 32)


def _event_hubs_sas_token(rng: random.Random) -> str:
    resource = f"https://{_namespace(rng)}.servicebus.windows.net/{_run(rng, _LOWER, 6)}"
    return (
        "SharedAccess"
        + "Signature sr="
        + quote(resource, safe="")
        + "&si"
        + "g="
        + quote(_b64_key(rng, 32), safe="")
        + f"&se={rng.randint(1_700_000_000, 1_900_000_000)}"
        + "&skn="
        + rng.choice(["RootManageSharedAccessKey", "send"])
    )


def _storage_sas_url(rng: random.Random) -> str:
    account = _account_name(rng)
    container = _run(rng, _LOWER, rng.randint(3, 12))
    blob = _run(rng, _LOWER + _DIGITS, rng.randint(3, 16)) + ".json"
    return f"https://{account}.blob.{_storage_suffix(rng)}/{container}/{blob}?{_sas_query(rng)}"


_PASSWORD_CHARS = _ALNUM + "!#$%^*_-+.~"


def _password(rng: random.Random, low: int = 8, high: int = 32) -> str:
    return _mixed(rng, _PASSWORD_CHARS, rng.randint(low, high))


def _url_with_userinfo(rng: random.Random) -> str:
    scheme = rng.choice(["https", "http", "postgresql", "mongodb+srv", "redis", "amqp", "ftp"])
    user = _run(rng, _LOWER, 1) + _run(rng, _ALNUM, rng.randint(2, 12))
    secret = _mixed(rng, _ALNUM + "-._~!$*", rng.randint(8, 24))
    host = _run(rng, _LOWER, rng.randint(3, 12)) + ".example.com"
    tail = rng.choice(["", ":5432/app", "/path", ":6380"])
    return f"{scheme}://{user}:{secret}@{host}{tail}"


def _url_with_at_in_username(rng: random.Random) -> str:
    """Azure Database for PostgreSQL single-server login: ``user@servername`` (raw ``@``)."""
    scheme = rng.choice(["postgresql", "postgres"])
    server = _run(rng, _LOWER, 1) + _run(rng, _LOWER + _DIGITS, rng.randint(3, 20))
    user = _run(rng, _LOWER, 1) + _run(rng, _ALNUM, rng.randint(2, 12))
    secret = _mixed(rng, _ALNUM + "-._~!$*", rng.randint(8, 24))
    suffix = rng.choice(["postgres.database.azure.com", "postgres.database.usgovcloudapi.net"])
    tail = rng.choice(["/db", ":5432/app", ""])
    return f"{scheme}://{user}@{server}:{secret}@{server}.{suffix}{tail}"


def _assignment(rng: random.Random, label: str, value: str) -> str:
    style = rng.randrange(4)
    if style == 0:
        return f"{label}={value}"
    if style == 1:
        return f"{label}: {value}"
    if style == 2:
        return f'"{label}": "{value}"'
    return f"{label} = '{value}'"


def _password_assignment(rng: random.Random) -> str:
    label = rng.choice(
        [
            "password",
            "Password",
            "passwd",
            "pwd",
            "passcode",
            "DB_PASSWORD",
            "secret",
            "api_key",
            "apiKey",
            "AppSecret",
            "token",
            "auth_token",
            "accessToken",
        ]
    )
    return _assignment(rng, label, _password(rng))


def _client_secret_assignment(rng: random.Random) -> str:
    label = rng.choice(["client_secret", "ClientSecret", "AppSecret", "AZURE_CLIENT_SECRET"])
    return _assignment(rng, label, _mixed(rng, _ALNUM + "-_.~", rng.randint(34, 40)))


def _header(rng: random.Random, names: list[str]) -> str:
    name = rng.choice(names)
    value = _run(rng, _HEX, 32)
    return rng.choice([f"{name}: {value}", f'"{name}": "{value}"', f"{name}={value}"])


def _azure_openai_api_key_header(rng: random.Random) -> str:
    return _header(rng, ["api-key", "Api-Key", "API-KEY"])


def _apim_subscription_key_header(rng: random.Random) -> str:
    return _header(rng, ["Ocp-Apim-Subscription-Key", "ocp-apim-subscription-key"])


def _apim_subscription_key_query(rng: random.Random) -> str:
    host = _run(rng, _LOWER, rng.randint(3, 12)) + ".azure-api.net"
    tail = rng.choice(["", "&api-version=2024-10-21"])
    return f"https://{host}/{_run(rng, _LOWER, 5)}?subscription-key={_run(rng, _HEX, 32)}{tail}"


def _opaque_secret(rng: random.Random) -> str:
    return _mixed(rng, _B64, rng.randint(40, 86)) + rng.choice(["", "=", "=="])


CREDENTIAL_GENERATORS: Mapping[str, Callable[[random.Random], str]] = MappingProxyType(
    {
        "private_key_block": _private_key_block,
        "private_key_block_truncated": _private_key_block_truncated,
        "jwt": _jwt,
        "bearer_token": _bearer_token,
        "aws_access_key_id": _aws_access_key_id,
        "github_pat_classic": _github_pat_classic,
        "github_oauth_or_app_token": _github_other_token,
        "github_fine_grained_pat": _github_fine_grained_pat,
        "github_app_installation_stateless": _github_app_installation_stateless,
        "openai_style_sk": _openai_style_sk,
        "sk_pk_underscore": _sk_pk_underscore,
        "slack_xoxb": _slack_token,
        "azure_storage_connection_string": _azure_storage_connection_string,
        "azure_storage_sas_connection_string": _azure_storage_sas_connection_string,
        "service_bus_connection_string": _service_bus_connection_string,
        "account_key_assignment": _account_key_assignment,
        "shared_access_key_assignment": _shared_access_key_assignment,
        "event_hubs_sas_token": _event_hubs_sas_token,
        "storage_sas_url": _storage_sas_url,
        "url_with_userinfo": _url_with_userinfo,
        "url_with_at_in_username": _url_with_at_in_username,
        "password_assignment": _password_assignment,
        "client_secret_assignment": _client_secret_assignment,
        "azure_openai_api_key_header": _azure_openai_api_key_header,
        "apim_subscription_key_header": _apim_subscription_key_header,
        "apim_subscription_key_query": _apim_subscription_key_query,
        "opaque_secret": _opaque_secret,
    }
)

EXPECTED_CATEGORY: Mapping[str, str] = MappingProxyType(
    {
        "private_key_block": "private_key",
        "private_key_block_truncated": "private_key",
        "jwt": "jwt",
        "bearer_token": "bearer_token",
        "aws_access_key_id": "cloud_access_key",
        "github_pat_classic": "vendor_api_key",
        "github_oauth_or_app_token": "vendor_api_key",
        "github_fine_grained_pat": "vendor_api_key",
        "github_app_installation_stateless": "vendor_api_key",
        "openai_style_sk": "vendor_api_key",
        "sk_pk_underscore": "vendor_api_key",
        "slack_xoxb": "vendor_api_key",
        "azure_storage_connection_string": "connection_string",
        "azure_storage_sas_connection_string": "connection_string",
        "service_bus_connection_string": "connection_string",
        "account_key_assignment": "connection_string",
        "shared_access_key_assignment": "connection_string",
        "event_hubs_sas_token": "connection_string",
        "storage_sas_url": "connection_string",
        "url_with_userinfo": "url_with_credentials",
        "url_with_at_in_username": "url_with_credentials",
        "password_assignment": "password_assignment",
        "client_secret_assignment": "password_assignment",
        "azure_openai_api_key_header": "vendor_api_key",
        "apim_subscription_key_header": "vendor_api_key",
        "apim_subscription_key_query": "vendor_api_key",
        "opaque_secret": "other",
    }
)

assert set(EXPECTED_CATEGORY) == set(CREDENTIAL_GENERATORS)
assert set(EXPECTED_CATEGORY.values()) <= ALL_CATEGORIES

_LABELLED_VALUE = frozenset(
    {
        "password_assignment",
        "client_secret_assignment",
        "azure_openai_api_key_header",
        "apim_subscription_key_header",
    }
)


def secret_value(kind: str, credential: str) -> str:
    """The part of ``credential`` that must not survive redaction (labels are kept)."""
    if kind == "bearer_token":
        return credential.split(None, 1)[1]
    if kind in _LABELLED_VALUE:
        for index, char in enumerate(credential):
            if char in "=:":
                return credential[index + 1 :].strip().strip("\"'")
    if kind == "apim_subscription_key_query":
        return credential.split("subscription-key=", 1)[1].split("&", 1)[0]
    if kind == "url_with_at_in_username":  # the server name also appears in the host
        return credential.split("://", 1)[1].rsplit("@", 1)[0].rsplit(":", 1)[1]
    if kind == "url_with_userinfo":
        return credential.split("://", 1)[1].rsplit("@", 1)[0]
    return credential


def NEGATIVE_LOOKALIKES(rng: random.Random) -> list[str]:  # noqa: N802 - stable public name
    """Strings that must not be reported by any credential or secret detector."""
    sha = _run(rng, _HEX, 40)
    bare_hex = _run(rng, _HEX, 32)
    guid = "-".join(_run(rng, _HEX, n) for n in (8, 4, 4, 4, 12))
    return [
        "max_tokens=4096",
        "prompt_tokens: 12",
        "completion_tokens: 345",
        "total_tokens=1024",
        f"token_count: {rng.randint(1, 999)}",
        "token_limit=8000",
        "max_token=4096",
        '"token_type": "Bearer"',
        "tokenizer: cl100k",
        "secret_name: storage-primary",
        "1.2.3",
        "v2.10.0-rc.1",
        "2026-11-24",
        "2026-11-24T10:00:00Z",
        "ok",
        "fine",
        "The quick brown fox jumps over the lazy dog while the operators review the weekly "
        "governance report and reset the password policy through the admin portal.",
        "Please reset your password via the portal.",
        "/usr/local/lib/python3.12/site-packages/neurosphere_core/classification/detectors/x.py",
        r"C:\Program Files\NeuroSphere\bin\neurosphere-api.exe",
        "src/Components/Button2/IndexPage/Story3/ExampleStories/Default",
        "getUserAccountSettingsForCurrentTenantV2Handler",
        "this-is-a-very-long-kebab-case-slug-for-a-blog-post-title",
        "MAX_RETRY_COUNT_FOR_THE_DEFAULT_POLICY_2",
        "a" * 64,
        "=" * 64,
        "https://example.com/path?query=1&page=2",
        "postgres://dbhost:5432/app",
        "pk_customer_order_id_index",
        "disk-" + "encryption-set",  # under 20 body characters: the validator accepts it
        "AccountName=" + _account_name(rng) + ";EndpointSuffix=core.windows.net",
        "Endpoint=sb://ns.servicebus.windows.net/;Authentication=Managed Identity",
        "config=enabled sig=true",
        sha,
        bare_hex,
        guid,
        " ".join(placeholder(cast("Category", c)) for c in sorted(ALL_CATEGORIES)),
        "password=" + placeholder("password_assignment"),
        "Bearer " + placeholder("bearer_token"),
        "Account" + "Key=" + placeholder("connection_string"),
        "api-key: " + placeholder("vendor_api_key"),
        placeholder("url_with_credentials") + "dbhost:5432/app",
    ]
