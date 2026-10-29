"""Gateway registry API (PRP-33 item 6): observe-mode APIM registration, preflight, inventory.

* :func:`register` -- router hook (prefix ``/api/v1/gateways``) for ``RouterRegistry``.
* :func:`configure_gateway_plane` / :func:`build_gateway_plane` -- install the plane (store, audit,
  ARM client factory) on ``app.state``; unset -> 503.
"""

from neurosphere_api.gateway.dependencies import (
    GatewayPlane,
    build_gateway_plane,
    configure_gateway_plane,
    get_gateway_plane,
)
from neurosphere_api.gateway.models import GatewayDetail, GatewayList, RegisterGatewayBody
from neurosphere_api.gateway.router import PREFIX, build_router, register
from neurosphere_api.gateway.service import GatewayApi, audit_chain_id
from neurosphere_api.gateway.settings import GatewaySettings

__all__ = [
    "PREFIX",
    "GatewayApi",
    "GatewayDetail",
    "GatewayList",
    "GatewayPlane",
    "GatewaySettings",
    "RegisterGatewayBody",
    "audit_chain_id",
    "build_gateway_plane",
    "build_router",
    "configure_gateway_plane",
    "get_gateway_plane",
    "register",
]
