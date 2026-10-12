"""IdentityScope has no public path from request-shaped input."""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path

import pytest
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.scope import IdentityScope

_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "contracts/schemas/scope/v1/examples/valid/identity-scope.viewer.json"
)


def _payload() -> dict[str, object]:
    return json.loads(_EXAMPLE.read_text(encoding="utf-8"))


def test_public_init_rejects_dict() -> None:
    with pytest.raises(TypeError):
        IdentityScope(_payload())
    with pytest.raises(TypeError):
        IdentityScope(**_payload())


def test_public_init_rejects_contract_model_and_forged_token() -> None:
    contract = ContractScope.model_validate(_payload())
    with pytest.raises(TypeError):
        IdentityScope(contract)
    with pytest.raises(TypeError):
        IdentityScope(object(), contract)


def test_no_pydantic_construction_paths() -> None:
    for name in ("model_validate", "model_construct", "model_validate_json", "parse_obj"):
        assert not hasattr(IdentityScope, name)


def test_private_hook_rejects_dict() -> None:
    with pytest.raises(TypeError):
        IdentityScope._from_verified_contract(_payload())  # type: ignore[arg-type]


def test_internal_hook_builds_immutable_view() -> None:
    contract = ContractScope.model_validate(_payload())
    scope = IdentityScope._from_verified_contract(contract)
    assert scope.scope_hash == contract.scope_hash
    assert scope.cloud == contract.cloud
    with pytest.raises(AttributeError):
        scope.cloud = "government"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        scope._contract = contract
    # Mutating the source or the exported copy cannot change the scope.
    exported = scope.to_contract()
    exported.customer_id = "other"
    contract.customer_id = "other"
    assert scope.customer_id != "other"


def test_copy_and_pickle_refused() -> None:
    scope = IdentityScope._from_verified_contract(ContractScope.model_validate(_payload()))
    with pytest.raises(TypeError):
        copy.copy(scope)
    with pytest.raises(TypeError):
        copy.deepcopy(scope)
    with pytest.raises(TypeError):
        pickle.dumps(scope)
