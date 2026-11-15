"""Per-domain admission control (PRP-21 round 2 item 1).

Installs a :class:`~neurosphere_core.admission.TokenBucketLimiter` on ``app.state.admission`` only
when ``NS_ADMISSION_ENABLED`` is true. ``authz.dependencies.require`` charges it after the
permission check passes. With enabled=true and no (or an unreadable) ``NS_ADMISSION_POLICY_FILE``
the conservative default applies and a warning is logged; it is never unlimited.

It reports no readiness component: admission is an operator control, not a platform dependency.
An invalid ``NS_ADMISSION_*`` value enables admission with the default quota (never off).
Test seam: ``ctx.overrides.backend("admission")`` (a prebuilt ``TokenBucketLimiter``).
"""

from __future__ import annotations

import logging
from typing import Final

from neurosphere_core.admission import TokenBucketLimiter, load_quota_policy
from pydantic import ValidationError

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec, ComponentUnavailableError
from neurosphere_api.runtime.settings import AdmissionSettings

__all__ = ["BUILDER", "COMPONENTS", "STATE_ATTRIBUTE", "build"]

COMPONENTS: Final = ()
STATE_ATTRIBUTE: Final = "admission"
_log = logging.getLogger("neurosphere_api.runtime")


def build(ctx: BuildContext) -> None:
    override = ctx.overrides.backend("admission")
    if override is not None:
        if not isinstance(override, TokenBucketLimiter):
            raise ComponentUnavailableError("admission_override_invalid")
        setattr(ctx.app.state, STATE_ATTRIBUTE, override)
        return
    try:
        conf = AdmissionSettings()
    except ValidationError:
        # An unreadable setting must never switch the limit off: serve with the conservative
        # default quota (builder exceptions are swallowed by the composition, so raising would
        # silently mean "no admission").
        _log.error("NS_ADMISSION_* settings invalid: admission enabled with the default quota")
        setattr(ctx.app.state, STATE_ATTRIBUTE, TokenBucketLimiter(load_quota_policy(None)))
        return
    if not conf.enabled:
        return
    if conf.policy_file is None:
        _log.warning("NS_ADMISSION_ENABLED without NS_ADMISSION_POLICY_FILE: default quota applies")
    policy = load_quota_policy(conf.policy_file)
    setattr(ctx.app.state, STATE_ATTRIBUTE, TokenBucketLimiter(policy))


BUILDER: Final = BuilderSpec("admission", COMPONENTS, build)
