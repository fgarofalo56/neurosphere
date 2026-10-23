"""Unit tests for the DR target safety rules. Unmarked: no network, no emulators."""

from __future__ import annotations

import ns_dr  # pyright: ignore[reportMissingImports]
import ns_dr_emulator  # pyright: ignore[reportMissingImports]
import ns_dr_safety as safety  # pyright: ignore[reportMissingImports]
import pytest

REMOTE_COSMOS = "https://example-account.documents.azure.com:443/"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8081",
        "http://127.0.0.1:10000/",
        "https://LOCALHOST/x",
        "http://[::1]:8081/",
    ],
)
def test_local_endpoints_are_local(url: str) -> None:
    assert safety.is_local_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        REMOTE_COSMOS,
        "http://localhost.evil.example/",
        "http://127.0.0.1.nip.io/",
        "https://evil.example/localhost",
        "http://evil.example/?h=127.0.0.1",
        "http://user@evil.example/",
        "not a url",
        "",
    ],
)
def test_lookalikes_and_remote_are_not_local(url: str) -> None:
    assert not safety.is_local_endpoint(url)


def test_all_local_needs_nothing() -> None:
    policy = safety.TargetPolicy(env={})
    assert safety.authorize(
        ["http://localhost:8081", "http://127.0.0.1:10000/"], policy, restore=True
    )


def test_non_local_refused_without_approval_env() -> None:
    policy = safety.TargetPolicy(target="prod-a", env={})
    with pytest.raises(safety.TargetRefusedError, match="NS_LIVE_APPROVED"):
        safety.authorize([REMOTE_COSMOS], policy, restore=False)


def test_non_local_refused_when_approval_value_is_not_one() -> None:
    policy = safety.TargetPolicy(target="prod-a", env={"NS_LIVE_APPROVED": "true"})
    with pytest.raises(safety.TargetRefusedError):
        safety.authorize([REMOTE_COSMOS], policy, restore=False)


def test_non_local_refused_without_target_flag() -> None:
    policy = safety.TargetPolicy(env={"NS_LIVE_APPROVED": "1"})
    with pytest.raises(safety.TargetRefusedError, match="--target"):
        safety.authorize([REMOTE_COSMOS], policy, restore=False)


def test_non_local_backup_allowed_with_both() -> None:
    policy = safety.TargetPolicy(target="prod-a", env={"NS_LIVE_APPROVED": "1"})
    assert safety.authorize([REMOTE_COSMOS], policy, restore=False) is False


@pytest.mark.parametrize("confirm", [None, "", "prod-b", "PROD-A"])
def test_non_local_restore_needs_matching_confirmation(confirm: str | None) -> None:
    policy = safety.TargetPolicy(
        target="prod-a", confirm_target=confirm, env={"NS_LIVE_APPROVED": "1"}
    )
    with pytest.raises(safety.TargetRefusedError, match="confirm-target"):
        safety.authorize([REMOTE_COSMOS], policy, restore=True)


def test_non_local_restore_allowed_with_matching_confirmation() -> None:
    policy = safety.TargetPolicy(
        target="prod-a", confirm_target="prod-a", env={"NS_LIVE_APPROVED": "1"}
    )
    assert safety.authorize([REMOTE_COSMOS], policy, restore=True) is False


def test_one_remote_endpoint_among_local_still_refuses() -> None:
    policy = safety.TargetPolicy(env={})
    with pytest.raises(safety.TargetRefusedError):
        safety.authorize(["http://localhost:8081", REMOTE_COSMOS], policy, restore=False)


def test_blob_endpoint_parsing() -> None:
    assert safety.is_local_endpoint(
        safety.blob_endpoint_from_connection_string("UseDevelopmentStorage=true;")
    )
    assert safety.is_local_endpoint(
        safety.blob_endpoint_from_connection_string("BlobEndpoint=http://127.0.0.1:10000/acct;")
    )
    assert not safety.is_local_endpoint(
        safety.blob_endpoint_from_connection_string(
            "AccountName=prodacct;EndpointSuffix=core.windows.net;"
        )
    )
    assert not safety.is_local_endpoint(
        safety.blob_endpoint_from_connection_string(
            "BlobEndpoint=https://prodacct.blob.core.windows.net/;"
        )
    )


@pytest.mark.parametrize("name", ["cost-ledger", "drill-", "prod-drill-x", "", "Drill-x"])
def test_drill_names_are_enforced(name: str) -> None:
    with pytest.raises(safety.TargetRefusedError):
        safety.require_drill_name(name)


def test_drill_name_accepted() -> None:
    assert safety.require_drill_name("drill-ab12cd34") == "drill-ab12cd34"


def _cli_env(**extra: str) -> dict[str, str]:
    return {"NS_COSMOS_ENDPOINT": REMOTE_COSMOS, **extra}


def test_cli_refuses_remote_cosmos_before_any_io(capsys: pytest.CaptureFixture[str]) -> None:
    code = ns_dr.main(["backup", "--out", "temp/never", "--database", "x"], env=_cli_env())
    assert code == ns_dr.EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_cli_refuses_remote_restore_without_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = ns_dr.main(
        ["restore", "--from", "temp/never", "--database", "x", "--target", "prod-a"],
        env=_cli_env(NS_LIVE_APPROVED="1"),
    )
    assert code == ns_dr.EXIT_REFUSED
    assert "confirm-target" in capsys.readouterr().err


def test_cli_refuses_remote_drill_without_approval(capsys: pytest.CaptureFixture[str]) -> None:
    code = ns_dr.main(["drill"], env=_cli_env())
    assert code == ns_dr.EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_cli_refuses_remote_blob_connection_string() -> None:
    env = {"NS_BLOB_CONNECTION_STRING": "AccountName=prodacct;EndpointSuffix=core.windows.net;"}
    code = ns_dr.main(["backup", "--out", "temp/never", "--database", "x"], env=env)
    assert code == ns_dr.EXIT_REFUSED


def test_default_connections_are_local() -> None:
    conn = ns_dr_emulator.load_connections({})
    args = ns_dr.build_parser().parse_args(["drill"])
    ns_dr.check_target(args, conn, {})  # raises TargetRefusedError if anything were non-local
    assert "AccountKey" not in repr(conn)
