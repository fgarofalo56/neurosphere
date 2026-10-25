"""Production composition root of the API (PRP-29 item 1).

``compose_app(app, settings, overrides=None)`` builds every store and service from settings,
calls ``configure_authz`` with the Entra token validator and the policy-store scope deriver,
and reports one status per component through the ``composition`` readiness probe. See
``compose.py`` for the sequence, ``builders/__init__.py`` for the builder interface and
``status.py`` for the readiness rules. ``main.create`` is the only production caller and never
passes ``overrides``.
"""

from neurosphere_api.runtime.compose import CONTAINER_STEP, STATE_ATTRIBUTE, compose_app
from neurosphere_api.runtime.cors import install_cors, load_cors_settings
from neurosphere_api.runtime.overrides import CompositionOverrides
from neurosphere_api.runtime.pseudonym import (
    LOCAL_DEV_PSEUDONYM_KEY_REFERENCE,
    local_dev_pseudonym_key,
    resolve_pseudonym_key,
)
from neurosphere_api.runtime.readiness import COMPOSITION_PROBE, ReadinessProbes
from neurosphere_api.runtime.settings import (
    LOCAL_DEFAULT_CUSTOMER_ID,
    AuthSettings,
    CorsSettings,
    StoreSettings,
)
from neurosphere_api.runtime.status import (
    OPTIONAL_COMPONENTS,
    REQUIRED_COMPONENTS,
    ComponentRegistry,
    ComponentState,
    ComponentStatus,
)

__all__ = [
    "COMPOSITION_PROBE",
    "CONTAINER_STEP",
    "LOCAL_DEFAULT_CUSTOMER_ID",
    "LOCAL_DEV_PSEUDONYM_KEY_REFERENCE",
    "OPTIONAL_COMPONENTS",
    "REQUIRED_COMPONENTS",
    "STATE_ATTRIBUTE",
    "AuthSettings",
    "ComponentRegistry",
    "ComponentState",
    "ComponentStatus",
    "CompositionOverrides",
    "CorsSettings",
    "ReadinessProbes",
    "StoreSettings",
    "compose_app",
    "install_cors",
    "load_cors_settings",
    "local_dev_pseudonym_key",
    "resolve_pseudonym_key",
]
