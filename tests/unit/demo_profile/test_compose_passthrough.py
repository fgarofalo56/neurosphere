"""PRP-71 item 4: the demo profile env file, its compose passthrough and the Makefile targets.

Offline: the compose file is parsed as YAML and its ``${VAR:-default}`` defaults are resolved with
an empty environment, so no Docker daemon is needed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
ENV_FILE = ROOT / "infra" / "dev" / "demo-profile.env"
MAKEFILE = ROOT / "Makefile"

# Same marker list as tests/unit/hosted_data_path/test_profile_parity.py.
SECRET_NAME = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|CONNECTION_?STRING|CREDENTIAL", re.IGNORECASE)

# Read by no API source file: the single copilot switch, consumed by compose (default path of
# NS_COPILOT_MODE), the demo check and the demo settings seed. PRP-78 set it to recorded.
UNREAD_BY_CODE = {
    "NS_DEMO_COPILOT_MODE": "consumed by compose and the demo check only (PRP-71/PRP-78)"
}

# env name -> services that must receive it.
EXPECTED_SERVICES = {
    "NS_INGEST_PRODUCER_STORE": ("api",),
    "NS_WORKER_REC_SOURCE": ("workers",),
    "NS_MCP_RESOURCE_SERVER_URL": ("api",),
    "NS_MCP_AUDIENCES": ("api",),
    "NS_MCP_ALLOWED_HOSTS": ("api",),
    "NS_SCAN_ENABLED": ("api",),
    "NS_LIFECYCLE_MODE": ("api", "workers"),
    "NS_DEMO_COPILOT_MODE": ("api",),
    # Found by the first live demo-up: the default pilot domain does not exist in the demo world.
    "NS_WORKER_EVAL_PILOT_DOMAIN_ID": ("workers",),
}

_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^${}]*))?\}")


def _parse_env_file(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        out[name] = value
    return out


def _resolve(value: Any) -> Any:
    """Resolve ``${VAR:-default}`` (nested allowed) with an empty environment."""
    if not isinstance(value, str):
        return value
    previous = None
    while previous != value:
        previous = value
        value = _DEFAULT.sub(lambda m: m.group(2) or "", value)
    return value


def _compose_text(text: str) -> dict[str, Any]:
    return yaml.safe_load(text)


def _resolved_env(compose: dict[str, Any], service: str) -> dict[str, Any]:
    env = compose["services"][service]["environment"]
    return {k: _resolve(v) for k, v in env.items()}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for top in ("services", "packages"):
        for p in (ROOT / top).rglob("*.py"):
            parts = set(p.relative_to(ROOT).parts)
            if parts & {"tests", ".venv", "node_modules"}:
                continue
            files.append(p)
    return files


def _code_reads(name: str, files: list[Path]) -> bool:
    """True when ``name`` appears literally or as a settings ``env_prefix`` + declared field."""
    for p in files:
        text = p.read_text(encoding="utf-8")
        if f'"{name}"' in text:
            return True
        for m in re.finditer(r'(?:env_prefix=|ENV_PREFIX: Final = )"([A-Z0-9_]+)"', text):
            prefix = m.group(1)
            if name.startswith(prefix):
                field = name[len(prefix) :].lower()
                if re.search(rf"^\s+{re.escape(field)}\s*:", text, re.MULTILINE):
                    return True
    return False


@pytest.fixture(scope="module")
def env_values() -> dict[str, str]:
    return _parse_env_file(ENV_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _compose_text(COMPOSE.read_text(encoding="utf-8"))


def test_env_file_names_are_the_expected_set(env_values: dict[str, str]) -> None:
    assert set(env_values) == set(EXPECTED_SERVICES)


def test_copilot_is_recorded_and_scan_lifecycle_values(env_values: dict[str, str]) -> None:
    assert env_values["NS_DEMO_COPILOT_MODE"] == "recorded"
    assert env_values["NS_LIFECYCLE_MODE"] == "dry_run"
    assert env_values["NS_SCAN_ENABLED"] == "true"
    assert env_values["NS_WORKER_REC_SOURCE"] == "archive"
    # the evaluation pilot must be a demo-world domain or the evaluation role refuses to start
    assert env_values["NS_WORKER_EVAL_PILOT_DOMAIN_ID"].endswith(":domain:finance")


def test_no_secret_shaped_names(env_values: dict[str, str]) -> None:
    for name in env_values:
        assert not SECRET_NAME.search(name), name


def test_env_file_is_loopback_only(env_values: dict[str, str]) -> None:
    for value in env_values.values():
        assert "localhost" not in value.lower()
        for url in re.findall(r"https?://[^\s\"',\]]+", value):
            assert urlsplit(url).hostname == "127.0.0.1", url
        for host in re.findall(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
            assert host == "127.0.0.1", host
    assert "127.0.0.1:8000" in env_values["NS_MCP_ALLOWED_HOSTS"]


def test_values_are_not_credential_shaped(env_values: dict[str, str]) -> None:
    for value in env_values.values():
        assert not re.search(r"[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-", value), "no tenant/client ids"
        assert "SharedAccessKey" not in value


@pytest.mark.parametrize("name", sorted(EXPECTED_SERVICES))
def test_name_is_read_by_code(name: str) -> None:
    if name in UNREAD_BY_CODE:
        assert UNREAD_BY_CODE[name]
        return
    assert _code_reads(name, _source_files()), f"{name} is not read by any settings class"


@pytest.mark.parametrize("name", sorted(EXPECTED_SERVICES))
def test_name_is_passed_through_to_the_reading_service(name: str, compose: dict[str, Any]) -> None:
    for service in EXPECTED_SERVICES[name]:
        env = compose["services"][service]["environment"]
        if name == "NS_DEMO_COPILOT_MODE":
            assert name in env["NS_COPILOT_MODE"]
        else:
            assert name in env, f"{service} does not receive {name}"


def test_default_render_is_unchanged_for_pre_existing_keys(compose: dict[str, Any]) -> None:
    """With nothing exported, every key main already had resolves to the same value."""
    try:
        base = subprocess.run(
            ["git", "show", "main:docker-compose.yml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("no main ref available to compare against")
        return  # unreachable (skip raises); tells static analysis base is bound below
    before = _compose_text(base)
    for service, spec in before["services"].items():
        old_env = spec.get("environment")
        if not isinstance(old_env, dict):
            continue
        new_env = compose["services"][service]["environment"]
        for key, old in old_env.items():
            assert _resolve(new_env[key]) == _resolve(old), f"{service}.{key}"
        assert spec.get("profiles") == compose["services"][service].get("profiles")


def test_new_passthrough_names_are_unset_by_default(compose: dict[str, Any]) -> None:
    """Value-less names are forwarded only when exported, so a plain `up` sets nothing new."""
    for name in ("NS_SCAN_ENABLED", "NS_LIFECYCLE_MODE", "NS_MCP_RESOURCE_SERVER_URL"):
        assert compose["services"]["api"]["environment"][name] is None
    assert compose["services"]["workers"]["environment"]["NS_LIFECYCLE_MODE"] is None
    assert _resolved_env(compose, "workers")["NS_WORKER_ROLES"] == "all"  # runs every role already
    assert _resolved_env(compose, "api")["NS_COPILOT_MODE"] == "disabled"


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(target)}:.*?(?=^\S)", text + "\nEND", re.MULTILINE | re.DOTALL)
    assert m, f"no {target} target"
    return m.group(0)


def test_demo_targets_exist() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    for target in ("demo-up", "demo-down", "demo-check"):
        assert re.search(rf"^{target}:", text, re.MULTILINE), target
    assert "sbx_demo_check.py" in _recipe("demo-check")


def test_demo_up_reuses_stack_up_with_the_demo_world_profile() -> None:
    recipe = _recipe("demo-up")
    assert "stack-up" in recipe
    assert "SEED_PROFILE=demo-world" in recipe
    assert "STACK_ENV_FILE=infra/dev/demo-profile.env" in recipe
    assert (ROOT / "infra" / "dev" / "demo-profile.env").is_file()


def test_stack_up_order_grants_only_then_app_then_full_seed() -> None:
    recipe = _recipe("stack-up")
    grants = recipe.index("SEED_ARGS=--grants-only")
    app_up = recipe.index("--profile app up")
    full = recipe.index("$(MAKE) seed-stack\n")
    assert grants < app_up < full
    assert recipe.index("--profile seed run") > full
    # The catalog seed container seeds the SAME profile: at its default (small) it replaced the
    # demo-world grants and the evaluation role lost its pilot domain.
    assert "seed python scripts/sandbox/sbx_seed_catalog.py --profile $(SEED_PROFILE)" in recipe
    # Env file applies to the compose app and seed lines and the host-side FULL seed; a plain
    # stack-up has none. The full seed reads NS_DEMO_COPILOT_MODE: without the profile it stored
    # the disabled copilot/search rows, which beat the environment after an API restart.
    assert recipe.count("$(STACK_ENV_LOAD)") == 3
    full_line = next(ln for ln in recipe.splitlines() if ln.endswith("$(MAKE) seed-stack"))
    assert full_line.lstrip().startswith("$(STACK_ENV_LOAD)")
    grants_line = next(ln for ln in recipe.splitlines() if "SEED_ARGS=--grants-only" in ln)
    assert "$(STACK_ENV_LOAD)" not in grants_line
    assert re.search(r"^STACK_ENV_FILE \?=\s*$", MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE)
