"""Generated bindings against the same golden examples (PRP-01 item 7, ADR-0004).

Python: every valid example round-trips through its generated Pydantic model
(``model_validate`` -> ``model_dump(mode="json", by_alias=True, exclude_unset=True)``
equals the input) and passes the cross-field Python validators. Every invalid example is
rejected by Pydantic or by the Python validators, and always by JSON Schema itself; the
ones Pydantic accepts must fail only on the conditional rules the codegen shape projection
deliberately drops, otherwise the generated model has lost a shape rule.

TypeScript: tests/contracts/ts/*.test.ts, run by ``pnpm --filter ./packages/contracts/ts
test`` (invoked below).
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import shutil
import subprocess
import sys
from typing import Any

import pytest
from contract_support import (
    REPO_ROOT,
    ExampleCase,
    invalid_cases,
    iter_error_tree,
    json_pointer,
    model_for,
    schema_errors,
    schema_files,
    valid_cases,
)
from pydantic import BaseModel, ValidationError
from validators import run_single_document_validators

# Valid examples that a named cross-field validator rejects. These are defects in the
# examples (not in the validator); each entry is a strict xfail so the suite turns red as
# soon as the example is fixed and the entry can be removed.
KNOWN_EXAMPLE_DEFECTS: dict[str, str] = {}

# Keywords the codegen shape projection removes (ADR-0004): Pydantic cannot enforce them.
PROJECTED_AWAY = frozenset({"if", "then", "else", "not", "contains"})


def _ids(cases: list[ExampleCase]) -> list[str]:
    return [c.case_id for c in cases]


def _pydantic_accepts(case: ExampleCase) -> bool:
    try:
        model_for(case.schema).model_validate(case.load())
    except ValidationError:
        return False
    return True


def _dropped_by_projection(schema_path: list[Any]) -> bool:
    """True when an error comes from a rule the shape projection removes: a conditional
    keyword, or a constraint-only ``allOf`` member (an ``anyOf``/``oneOf`` with no type)."""
    parts = [str(p) for p in schema_path]
    if PROJECTED_AWAY & set(parts):
        return True
    return any(
        parts[i] == "allOf" and i + 2 < len(parts) and parts[i + 2] in ("anyOf", "oneOf")
        for i in range(len(parts))
    )


@pytest.mark.parametrize("rel", schema_files())
def test_every_schema_has_a_generated_model(rel: str) -> None:
    model = model_for(rel)
    assert issubclass(model, BaseModel)


def test_generated_models_forbid_extra_properties() -> None:
    """Clarification 6: generated Pydantic models set extra="forbid"."""
    import neurosphere_contracts

    loose = []
    for info in pkgutil.walk_packages(neurosphere_contracts.__path__, "neurosphere_contracts."):
        module = importlib.import_module(info.name)
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
                and "root" not in obj.model_fields
                and obj.model_config.get("extra") != "forbid"
            ):
                loose.append(f"{module.__name__}.{obj.__name__}")
    assert not loose, f"models without extra='forbid': {loose}"


def _params_with_defects(cases: list[ExampleCase]) -> list[Any]:
    params = []
    for case in cases:
        marks = []
        if case.case_id in KNOWN_EXAMPLE_DEFECTS:
            marks.append(pytest.mark.xfail(reason=KNOWN_EXAMPLE_DEFECTS[case.case_id], strict=True))
        params.append(pytest.param(case, id=case.case_id, marks=marks))
    return params


@pytest.mark.parametrize("case", valid_cases(), ids=_ids(valid_cases()))
def test_valid_example_round_trips_through_pydantic(case: ExampleCase) -> None:
    document = case.load()
    model = model_for(case.schema).model_validate(document)
    dumped = model.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert dumped == document


@pytest.mark.parametrize("case", _params_with_defects(valid_cases()))
def test_valid_example_passes_python_validators(
    case: ExampleCase, validator_context: dict[str, Any]
) -> None:
    assert run_single_document_validators(case.schema, case.load(), validator_context) == []


@pytest.mark.parametrize("case", invalid_cases(), ids=_ids(invalid_cases()))
def test_invalid_example_is_rejected(case: ExampleCase, validator_context: dict[str, Any]) -> None:
    document = case.load()
    errors = schema_errors(case.schema, document)
    assert errors, "JSON Schema (the source of truth) must reject every invalid example"
    if not _pydantic_accepts(case):
        return
    # Pydantic accepted it, so rejection rests on JSON Schema (plus any Python validator).
    # That is only legitimate for rules the codegen shape projection drops; any other
    # failing rule means the generated model lost a shape constraint.
    shape_errors = [
        f"{json_pointer(e.absolute_path)} {e.validator} via "
        + "/".join(map(str, e.absolute_schema_path))
        for e in errors
        if not _dropped_by_projection(list(e.absolute_schema_path))
    ]
    assert not shape_errors, f"Pydantic missed shape rules: {shape_errors}"
    run_single_document_validators(case.schema, document, validator_context)  # must not raise


def test_pydantic_gap_is_measured() -> None:
    """ADR-0004 records how many invalid examples the Pydantic models accept (all of them
    cross-field conditionals). Report the current figure; JSON Schema rejects all."""
    accepted = [c for c in invalid_cases() if _pydantic_accepts(c)]
    rejected_by_schema = [
        c for c in accepted if any(iter_error_tree(schema_errors(c.schema, c.load())))
    ]
    assert rejected_by_schema == accepted
    assert len(accepted) < len(invalid_cases())
    print(
        f"\nPydantic accepts {len(accepted)} of {len(invalid_cases())} invalid examples "
        f"({len(valid_cases())} valid); JSON Schema rejects all {len(accepted)}."
    )


def _typescript_toolchain() -> str | None:
    pnpm = shutil.which("pnpm")
    vitest = REPO_ROOT / "packages" / "contracts" / "ts" / "node_modules" / "vitest"
    if pnpm is None or shutil.which("node") is None or not vitest.exists():
        return None
    return pnpm


def test_typescript_round_trip_runs_under_pnpm() -> None:
    """Runs tests/contracts/ts/*.test.ts through the package's own vitest config."""
    pnpm = _typescript_toolchain()
    if pnpm is None:
        message = "pnpm/node or packages/contracts/ts node_modules missing (pnpm install)"
        if os.environ.get("NS_CODEGEN_REQUIRED") == "1":
            pytest.fail(f"NS_CODEGEN_REQUIRED=1 but {message}")
        pytest.skip(message)
    env = {**os.environ, "CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"}
    proc = subprocess.run(
        [pnpm, "--filter", "./packages/contracts/ts", "test"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=600,
        check=False,
    )
    output = proc.stdout + proc.stderr
    sys.stdout.write(output[-2000:])
    assert proc.returncode == 0, output[-4000:]
    assert "No test files found" not in output
    assert "passed" in output
