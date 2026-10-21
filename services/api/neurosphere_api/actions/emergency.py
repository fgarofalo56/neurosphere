"""Emergency disable (kill switch) read and change, per customer (PRP-17 item 4).

Backed by :class:`~neurosphere_core.actions.ExecutionControl`. Fail closed: a control store that
cannot be read is ``dependency_transient`` (503), never "enabled". Changing the switch is
audited through the PRP-06 hash-chained store (``before`` record first, then the write, then the
``after`` record; a failed audit write aborts the change). The audit chain is
``<customer>.execution-control`` and the subject ``<cloud>:<customer>:neurosphere:
execution_control:<customer>``. Disabling never touches intents: queued and executing ones
resume through the normal recheck once execution is enabled again.
"""

from __future__ import annotations

from typing import Final

from neurosphere_core.actions import ExecutionControlState
from neurosphere_core.actions.control import control_unavailable
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    build_after,
    build_before,
    make_subject,
    run_audited_mutation,
)
from neurosphere_core.errors import NeuroSphereError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.actions.dependencies import ActionPlane
from neurosphere_api.actions.models import EmergencyDisableBody, EmergencyDisableView

__all__ = ["CONTROL_ENTITY_TYPE", "control_chain_id", "read_control", "set_control"]

CONTROL_ENTITY_TYPE: Final = "execution_control"


def control_chain_id(customer_id: str) -> str:
    return f"{customer_id}.execution-control"


def _view(state: ExecutionControlState) -> EmergencyDisableView:
    return EmergencyDisableView(
        disabled=state.disabled,
        reason=state.reason,
        changed_by=state.changed_by,
        changed_at=state.changed_at,
    )


async def read_control(plane: ActionPlane, scope: IdentityScope) -> EmergencyDisableView:
    try:
        state = await plane.control.get(scope.customer_id)
    except NeuroSphereError:
        raise
    except Exception as exc:
        raise control_unavailable() from exc
    return _view(state)


async def set_control(
    plane: ActionPlane, scope: IdentityScope, body: EmergencyDisableBody, correlation_id: str
) -> EmergencyDisableView:
    customer = scope.customer_id
    ctx = AuditContext.from_scope(
        scope,
        correlation_id=correlation_id,
        operation="action.emergency_disable" if body.disabled else "action.emergency_enable",
        channel="rest",
    )
    subject_id = f"{scope.cloud}:{customer}:neurosphere:{CONTROL_ENTITY_TYPE}:{customer}"
    requested = {"disabled": body.disabled, "reason": body.reason}
    changed_by = ctx.actor.principal_pseudonym

    async def mutate() -> ExecutionControlState:
        try:
            return await plane.control.set(
                customer,
                disabled=body.disabled,
                reason=body.reason,
                changed_by=changed_by,
                now=plane.now(),
            )
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise control_unavailable() from exc

    def after(state: ExecutionControlState) -> AuditDraft:
        subject = make_subject(
            subject_id,
            CONTROL_ENTITY_TYPE,
            state={"disabled": state.disabled, "reason": state.reason},
        )
        detail = "kill_switch=disabled" if state.disabled else "kill_switch=enabled"
        return build_after(ctx, subject, result="succeeded", verified=True, detail=detail)

    def failed(exc: BaseException) -> AuditDraft:
        subject = make_subject(subject_id, CONTROL_ENTITY_TYPE, state=requested)
        code = getattr(exc, "reason", None) or "error"
        return build_after(ctx, subject, result="failed", verified=False, detail=str(code))

    state = await run_audited_mutation(
        plane.audit,
        control_chain_id(customer),
        before=build_before(ctx, make_subject(subject_id, CONTROL_ENTITY_TYPE, state=requested)),
        mutate=mutate,
        after=after,
        on_error=failed,
    )
    return _view(state)
