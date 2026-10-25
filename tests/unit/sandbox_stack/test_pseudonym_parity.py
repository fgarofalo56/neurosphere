"""PRP-29 item 10: the worker's pseudonym-key resolution equals the API's.

The workers mirror ``neurosphere_api.runtime.resolve_pseudonym_key`` instead of importing it
(workers may not import ``services/api``). If the two ever drift, the worker principal that the
seed grants (and that the worker derives its own scope from) stops matching the principal the API
and ``sbx_grant_operator`` compute for the same tenant and object id, and every worker read
answers an empty scope. This pins both resolutions to the same key and the same principal ids.
"""

from __future__ import annotations

import pytest
from neurosphere_api.runtime import AuthSettings as ApiAuthSettings
from neurosphere_api.runtime import resolve_pseudonym_key as api_resolve
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope import PrincipalPseudonymizer, PseudonymKey
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import NeuroSphereError
from neurosphere_workers.runtime.identity import resolve_pseudonym_key as worker_resolve
from neurosphere_workers.runtime.roles import RoleConfigError
from neurosphere_workers.runtime.settings import AuthSettings as WorkerAuthSettings
from pydantic import SecretStr

TENANT = normalize_tenant_id("0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
OBJECT_ID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OTHER_OBJECT_ID = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8c9"
REFERENCE = "https://ns-parity-test.vault.azure.net/secrets/principal-pseudonym-key"
PROBE = b"parity-probe"


def _explicit_material() -> str:
    # Assembled at runtime: no key-shaped literal in source.
    return "-".join(("parity", "material", "x" * 40))


def _keys(*, with_key: bool) -> tuple[PseudonymKey, PseudonymKey]:
    if with_key:
        api = ApiAuthSettings(
            pseudonym_key=SecretStr(_explicit_material()), pseudonym_key_reference=REFERENCE
        )
        worker = WorkerAuthSettings(
            pseudonym_key=SecretStr(_explicit_material()), pseudonym_key_reference=REFERENCE
        )
    else:
        api, worker = ApiAuthSettings(), WorkerAuthSettings()
    return api_resolve(api, env="local"), worker_resolve(worker, env="local")


@pytest.mark.parametrize("with_key", [False, True], ids=["local-dev-key", "explicit-key"])
def test_same_key_and_same_principal_ids(with_key: bool) -> None:
    api_key, worker_key = _keys(with_key=with_key)
    assert api_key.reference == worker_key.reference
    assert api_key.digest(PROBE) == worker_key.digest(PROBE)
    api_ids, worker_ids = PrincipalPseudonymizer(api_key), PrincipalPseudonymizer(worker_key)
    for cloud in (CloudName.COMMERCIAL, CloudName.GOVERNMENT):
        for kind in ("user", "service_principal"):
            for oid in (OBJECT_ID, OTHER_OBJECT_ID):
                args = {
                    "cloud": cloud,
                    "customer_id": "synthco",
                    "tenant_id": TENANT,
                    "object_id": oid,
                    "kind": kind,
                }
                assert api_ids.principal_id(**args) == worker_ids.principal_id(**args)  # type: ignore[arg-type]
    assert api_ids.pseudonym(TENANT, OBJECT_ID) == worker_ids.pseudonym(TENANT, OBJECT_ID)


def test_explicit_key_differs_from_the_local_dev_key() -> None:
    dev_api, dev_worker = _keys(with_key=False)
    explicit_api, explicit_worker = _keys(with_key=True)
    assert dev_api.digest(PROBE) != explicit_api.digest(PROBE)
    assert dev_worker.digest(PROBE) != explicit_worker.digest(PROBE)


def test_both_refuse_a_missing_key_outside_local() -> None:
    with pytest.raises(NeuroSphereError):
        api_resolve(ApiAuthSettings(), env="hosted")
    with pytest.raises(RoleConfigError):
        worker_resolve(WorkerAuthSettings(), env="hosted")
