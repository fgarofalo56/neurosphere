"""PRP-06 live run: validate a real Entra access token with the production JWT validator.

Operator-approved only. Refuses unless NS_LIVE_APPROVED=1 (checked first, before any import of
project code or network access).

Environment:
  NS_LIVE_APPROVED=1       required approval gate
  NS_P06_CLOUD             commercial | government (must match the active `az` cloud)
  NS_P06_TENANT_ID         tenant GUID that owns the API app registration
  NS_P06_API_APP_ID        API app (client) id GUID; the token resource is api://<id>

The token comes from `az account get-access-token` and lives only in this process: it is never
printed, logged or written. The evidence file records issuer shape, token version, audience form
and accept/reject outcomes, never identities or token material.
Writes docs/evidence/PRP-06/live-<cloud>-<date>.md.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUID_LEN = 36


def _refuse() -> int:
    print(
        "REFUSED: prp06_entra_live.py needs operator approval; set NS_LIVE_APPROVED=1. "
        "No connection was attempted.",
        file=sys.stderr,
    )
    return 2


def _mint_token(app_id: str, tenant_id: str) -> str:
    resource = f"api://{app_id}"
    cmd = [
        "az", "account", "get-access-token", "--resource", resource, "--tenant", tenant_id,
        "--query", "accessToken", "-o", "tsv",
    ]  # fmt: skip
    # shell=True on Windows only so `az.cmd` resolves; arguments are fixed strings plus two GUIDs.
    done = subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=120, shell=os.name == "nt"
    )
    if done.returncode != 0:
        raise SystemExit(f"az could not mint a token (exit {done.returncode}); are you logged in?")
    return done.stdout.strip()


def _outcome(exc: BaseException) -> str:
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    reason = getattr(exc, "reason", None)
    return f"{type(exc).__name__} status={status} reason={reason}"


async def _run(cloud_name: str, tenant: str, app_id: str) -> list[tuple[str, str, bool]]:
    import httpx
    from neurosphere_core.auth.jwt import JwtConfig, create_jwt_validator
    from neurosphere_core.cloud import CloudName

    cloud = CloudName(cloud_name)
    other = CloudName.GOVERNMENT if cloud is CloudName.COMMERCIAL else CloudName.COMMERCIAL
    token = _mint_token(app_id, tenant)
    audiences = (app_id, f"api://{app_id}")
    rows: list[tuple[str, str, bool]] = []

    def cfg(c: CloudName, t: str, aud: tuple[str, ...]) -> JwtConfig:
        return JwtConfig(env="prod", cloud=c, tenant_id=t, audiences=aud)

    async with httpx.AsyncClient() as http:
        good = create_jwt_validator(cfg(cloud, tenant, audiences), http)
        claims = await good.validate(token)
        rows.append(
            (
                "valid live token accepted",
                f"issuer_kind={claims.issuer_kind} ver={claims.token_version} cloud={claims.cloud} "
                f"audience_is_guid={claims.audience == app_id} issuer_is_v2="
                f"{claims.issuer == f'https://{_login_host(cloud)}/{tenant}/v2.0'} "
                f"scopes={list(claims.scopes)}",
                True,
            )
        )

        cases = [
            (
                "wrong audience rejected",
                cfg(cloud, tenant, ("00000000-0000-4000-8000-000000000001",)),
                token,
            ),
            (
                "wrong tenant rejected",
                cfg(cloud, "00000000-0000-4000-8000-000000000002", audiences),
                token,
            ),
            ("other cloud's authority rejected", cfg(other, tenant, audiences), token),
            ("tampered payload rejected", cfg(cloud, tenant, audiences), _tamper(token)),
            ("empty token rejected", cfg(cloud, tenant, audiences), ""),
        ]
        for name, config, tok in cases:
            validator = create_jwt_validator(config, http)
            try:
                await validator.validate(tok)
            except Exception as exc:
                rows.append((name, _outcome(exc), True))
            else:
                rows.append((name, "ACCEPTED (must never happen)", False))
    return rows


def _tamper(token: str) -> str:
    head, payload, sig = token.split(".")
    flipped = "A" if payload[10] != "A" else "B"
    return ".".join((head, payload[:10] + flipped + payload[11:], sig))


def _login_host(cloud: object) -> str:
    return "login.microsoftonline.us" if str(cloud) == "government" else "login.microsoftonline.com"


def main() -> int:
    if os.environ.get("NS_LIVE_APPROVED") != "1":
        return _refuse()
    cloud = os.environ.get("NS_P06_CLOUD", "").strip().lower()
    tenant = os.environ.get("NS_P06_TENANT_ID", "").strip().lower()
    app_id = os.environ.get("NS_P06_API_APP_ID", "").strip().lower()
    if (
        cloud not in {"commercial", "government"}
        or len(tenant) != GUID_LEN
        or len(app_id) != GUID_LEN
    ):
        print(
            "ERROR: set NS_P06_CLOUD, NS_P06_TENANT_ID and NS_P06_API_APP_ID (GUIDs).",
            file=sys.stderr,
        )
        return 2

    sys.path.insert(0, str(REPO / "packages" / "core"))
    rows = asyncio.run(_run(cloud, tenant, app_id))

    today = datetime.now(UTC).date().isoformat()
    out = REPO / "docs" / "evidence" / "PRP-06" / f"live-{cloud}-{today}.md"
    ok = all(passed for _, _, passed in rows)
    lines = [
        f"# PRP-06 live Entra validation: {cloud} ({today})",
        "",
        f"Operator-approved live run (NS_LIVE_APPROVED=1). Tenant `{tenant}`, API app `{app_id}`.",
        "A delegated user token was minted with `az` and validated by the production validator",
        "against live JWKS. No token, identity, oid or UPN is recorded here.",
        "",
        "| Check | Outcome | Pass |",
        "|---|---|---|",
        *[f"| {n} | {o} | {'yes' if p else 'NO'} |" for n, o, p in rows],
        "",
        "Reading the rejections: wrong audience and tampered payload are 401s from the",
        "validator's own checks. 'Wrong tenant' and 'other cloud' are rejected as 502",
        "jwks_unavailable (fail closed) because no JWKS exists for that tenant or authority;",
        "they do NOT exercise the issuer comparison,",
        "which the unit tests cover with local keys (packages/core/tests/auth/jwt).",
        "",
        "Not covered: expiry (needs a wait), app-only tokens, Government v1 issuer shape.",
        "This is not an authorization, ATO or compliance claim.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    for n, o, p in rows:
        print(f"{'PASS' if p else 'FAIL'}  {n}: {o}")
    print(f"evidence: {out.relative_to(REPO)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
