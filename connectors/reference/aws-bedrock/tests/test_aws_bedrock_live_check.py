"""PRP-62 item 6: README policy equals the constant; the live-check script refuses safely."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector_aws_bedrock.connector import AwsBedrockConnector
from neurosphere_connector_aws_bedrock.iam import IAM_POLICY
from neurosphere_connector_aws_bedrock.manifest import IAM_ACTIONS
from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow
from neurosphere_connector_aws_bedrock.reader import ReaderPage
from neurosphere_core.cloud.profile import CloudName

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "live_check.py"
README = ROOT / "README.md"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("aws_bedrock_live_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["aws_bedrock_live_check"] = module
    spec.loader.exec_module(module)
    return module


def test_readme_policy_block_equals_the_constant() -> None:
    text = README.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    assert [json.loads(b) for b in blocks] == [IAM_POLICY]


def test_policy_has_only_the_verified_read_actions() -> None:
    actions = IAM_POLICY["Statement"][0]["Action"]
    assert actions == list(IAM_ACTIONS)
    assert len(IAM_POLICY["Statement"]) == 1
    assert IAM_POLICY["Statement"][0]["Effect"] == "Allow"
    for action in actions:
        assert action.split(":", 1)[1].startswith(("List", "Get")), action
        assert "Invoke" not in action
        assert "Converse" not in action


def test_readme_documents_cost_warning_and_the_live_command() -> None:
    text = README.read_text(encoding="utf-8")
    assert "0.01 USD" in text
    assert "NS_LIVE_APPROVED=1" in text
    assert "connectors/reference/aws-bedrock/scripts/live_check.py" in text
    assert "G04 stays OPEN" in text.replace("\n", " ") or "G04" in text


def _run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    code = "\n".join(
        [
            "import runpy, sys",
            f"sys.argv = {[str(SCRIPT), *args]!r}",
            "code = 0",
            "try:",
            f"    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')",
            "except SystemExit as exc:",
            "    code = exc.code",
            "heavy = [m for m in ('boto3', 'botocore', 'neurosphere_connector_aws_bedrock')"
            " if m in sys.modules]",
            "print('EXIT', code, 'IMPORTED', heavy)",
        ]
    )
    import os

    env = {k: v for k, v in os.environ.items() if k != "NS_LIVE_APPROVED"}
    env.update(env_extra)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, env=env, check=False
    )


def test_refuses_without_approval_before_importing_the_sdk() -> None:
    proc = _run(["--region", "us-east-1", "--auth", "static-key"], {})
    assert "EXIT 2 IMPORTED []" in proc.stdout, proc.stderr
    assert "REFUSED" in proc.stderr
    assert "No connection was attempted" in proc.stderr


def test_refuses_any_value_other_than_one() -> None:
    proc = _run(["--region", "us-east-1", "--auth", "static-key"], {"NS_LIVE_APPROVED": "true"})
    assert "EXIT 2" in proc.stdout


def test_approved_but_no_budget_cap_is_refused_without_a_request() -> None:
    proc = _run(
        ["--region", "us-east-1", "--auth", "static-key"],
        {"NS_LIVE_APPROVED": "1", "NS_AWS_BEDROCK_KEY_JSON": "{}"},
    )
    assert "EXIT 2" in proc.stdout, proc.stderr
    assert "--budget-cap-usd" in proc.stderr


def test_approved_static_key_without_the_env_var_is_refused() -> None:
    proc = _run(
        ["--region", "us-east-1", "--auth", "static-key", "--budget-cap-usd", "1"],
        {"NS_LIVE_APPROVED": "1", "NS_AWS_BEDROCK_KEY_JSON": ""},
    )
    assert "EXIT 2" in proc.stdout, proc.stderr
    assert "NS_AWS_BEDROCK_KEY_JSON" in proc.stderr


def test_evidence_dir_outside_the_working_directory_is_refused() -> None:
    proc = _run(
        [
            "--region",
            "us-east-1",
            "--auth",
            "static-key",
            "--budget-cap-usd",
            "1",
            "--evidence-dir",
            "../../outside",
        ],
        {"NS_LIVE_APPROVED": "1", "NS_AWS_BEDROCK_KEY_JSON": "{}"},
    )
    assert "EXIT 2" in proc.stdout, proc.stderr
    assert "--evidence-dir" in proc.stderr


def test_govcloud_region_is_refused_even_when_approved() -> None:
    proc = _run(
        ["--region", "us-gov-west-1", "--auth", "static-key", "--budget-cap-usd", "1"],
        {"NS_LIVE_APPROVED": "1", "NS_AWS_BEDROCK_KEY_JSON": "{}"},
    )
    assert "EXIT 2" in proc.stdout, proc.stderr


# ------------------------------------------------------------------ evidence is whitelisted


class _Reader:
    async def list_foundation_models(self, *, limit: int) -> ReaderPage:
        return ReaderPage(
            items=({"id": "acme.secret-model-name", "name": "Secret Project Falcon"},)
        )

    async def list_custom_models(self, *, limit: int) -> ReaderPage:
        return ReaderPage(items=())

    list_provisioned_throughput = list_guardrails = list_agents = list_custom_models

    async def get_usage(
        self, *, model_ids: Sequence[str], window: UsageWindow, limit: int
    ) -> ReaderPage:
        return ReaderPage(items=())

    async def get_cost(
        self, *, window: CostWindow, services: Sequence[str], limit: int
    ) -> ReaderPage:
        return ReaderPage(
            items=(
                {
                    "day": window.start,
                    "service": "Amazon Bedrock",
                    "amount": "1234.56",
                    "currency": "USD",
                    "estimated": True,
                },
            )
        )

    async def get_invocation_logging(self) -> Mapping[str, Any]:
        return {"cloudwatch": True, "s3": False, "log_group": "/aws/bedrock/prod"}

    async def close(self) -> None:
        return None


async def test_evidence_holds_counts_only() -> None:
    script = _load_script()
    connector = AwsBedrockConnector(
        reader=_Reader(), cloud=CloudName.COMMERCIAL, region="us-east-1"
    )
    record, ok = await script.run_checks(
        connector, region="us-east-1", auth="static-key", max_pages=2
    )
    assert ok is True
    blob = json.dumps(record)
    for leaked in ("Falcon", "acme.secret-model-name", "1234.56", "/aws/bedrock/prod"):
        assert leaked not in blob
    assert record["inventory"]["foundation_models"] == 1
    assert record["cost"] == {"days": 1, "reported": 1}
    assert record["invocation_logging_configured"] is True
    assert set(record) == {
        "gate",
        "connector",
        "observed_at",
        "region",
        "auth",
        "contract_violations",
        "inventory",
        "usage",
        "cost",
        "invocation_logging_configured",
        "page_budget",
        "note",
    }


def test_script_imports_only_os_and_sys_at_top_level() -> None:
    top = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert top == ["from __future__ import annotations", "import os", "import sys"]


@pytest.mark.parametrize("name", ["README.md", "scripts/live_check.py"])
def test_no_credential_shaped_text_is_committed(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY", text)
