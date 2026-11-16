"""PRP-58 item 3: every new data path ``NS_*`` name appears in compose, Helm and Bicep.

None of the names may look like a secret: values are switches, roles and URLs, never credentials.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]

NEW_NAMES = (
    "NS_INGEST_PRODUCER_STORE",
    "NS_WORKER_CONNECTOR_CONFIG_SOURCE",
    "NS_API_BASE_URL",
    "NS_WORKER_REC_SOURCE",
    "NS_WORKER_ROLES",
)
SECRET_NAME = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|CONNECTION_?STRING|CREDENTIAL", re.IGNORECASE)

COMPOSE = ROOT / "docker-compose.yml"
HELM = (ROOT / "infra" / "helm" / "templates" / "deployment.yaml",)
BICEP = (ROOT / "infra" / "demo" / "main.bicep", ROOT / "infra" / "appservice" / "main.bicep")


def _text(paths: tuple[Path, ...]) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


@pytest.mark.parametrize("name", NEW_NAMES)
def test_name_is_in_every_profile(name: str) -> None:
    assert name in COMPOSE.read_text(encoding="utf-8"), "compose"
    assert name in _text(HELM), "helm"
    assert name in _text(BICEP), "bicep"


@pytest.mark.parametrize("name", NEW_NAMES)
def test_name_is_not_secret_shaped(name: str) -> None:
    assert not SECRET_NAME.search(name)


def test_compose_parses_and_passes_the_switches_to_the_right_services() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api = compose["services"]["api"]["environment"]
    workers = compose["services"]["workers"]["environment"]
    assert api["NS_INGEST_PRODUCER_STORE"] == "${NS_INGEST_PRODUCER_STORE:-false}"
    assert workers["NS_WORKER_REC_SOURCE"] == "${NS_WORKER_REC_SOURCE:-sandbox}"
    assert workers["NS_WORKER_CONNECTOR_CONFIG_SOURCE"].endswith(":-auto}")
    # Defaults are the code defaults, so compose behaviour is unchanged.
    assert workers["NS_API_BASE_URL"] == "${NS_API_BASE_URL:-}"


def test_no_profile_defaults_a_connector_role_on() -> None:
    values = yaml.safe_load((ROOT / "infra" / "helm" / "values.yaml").read_text(encoding="utf-8"))
    assert not values["workers"]["roles"]
    demo = (ROOT / "infra" / "demo" / "main.bicep").read_text(encoding="utf-8")
    assert "param connectorRoles array = []" in demo
    appservice = (ROOT / "infra" / "appservice" / "main.bicep").read_text(encoding="utf-8")
    assert "param workerRoles array = []" in appservice
