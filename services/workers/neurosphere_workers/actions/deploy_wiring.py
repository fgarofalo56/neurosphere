"""Builds the executor worker's deploy collaborators (PRP-55 item 4).

Called by the ``actions`` role when ``NS_DEPLOY_APPLY_ENABLED`` is set and
``NS_DEPLOY_APPLY_REGISTER_CONTAINER`` names the register container: the durable approvals
(``deploy_plan_approvals``, written by the API), the Cosmos register, and the ARM and Fabric
provisioners over one bearer transport bound to the deployment cloud. Fabric is wired only where
its endpoint set can be built (Government needs a verified token scope, #39: fail closed); the
capability matrix still decides per region inside the connector. The credential is the lazy one
of the composition, so nothing authenticates until an approved apply runs.

Only the worker imports this module: the API stays on the dry-run path
(``neurosphere_workers.actions.deploy.PlanOnlyArmProvisioner``) and never loads the transport.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from azure.cosmos.aio import CosmosClient
from neurosphere_core.cloud import CloudName, CloudProfile
from neurosphere_core.deploy.approvals.cosmos_store import CosmosPlanApprovalRepository
from neurosphere_core.deploy.fabric import FabricEndpoints, FabricProvisioner, fabric_endpoints_for
from neurosphere_core.deploy.register import RegisterStore
from neurosphere_core.deploy.register.cosmos_store import CosmosRegisterStore
from neurosphere_core.errors import InvalidSchemaError

from neurosphere_workers.actions.deploy import FabricHttpObserver, PlanApprovals
from neurosphere_workers.actions.deploy_approvals import RepositoryPlanApprovals
from neurosphere_workers.actions.deploy_arm import HttpArmProvisioner
from neurosphere_workers.actions.deploy_http import BearerDeployHttp, deploy_scopes

__all__ = ["DeployCollaborators", "build_deploy_collaborators", "worker_fabric_endpoints"]


@dataclass(frozen=True, slots=True)
class DeployCollaborators:
    approvals: PlanApprovals
    register: RegisterStore
    arm: HttpArmProvisioner
    fabric: FabricProvisioner | None
    observer: FabricHttpObserver | None


def worker_fabric_endpoints(cloud: CloudName) -> FabricEndpoints | None:
    """The Fabric endpoint set of ``cloud``, or ``None`` when it cannot be built (fail closed)."""
    try:
        return fabric_endpoints_for(cloud)
    except InvalidSchemaError:
        return None


def build_deploy_collaborators(
    *,
    profile: CloudProfile,
    cosmos: CosmosClient,
    database: str,
    register_container: str,
    http_client: httpx.AsyncClient,
    credential: Callable[[], AsyncTokenCredential],
) -> DeployCollaborators:
    """Everything the worker's ``DeployConnector`` needs; no network call is made here."""
    endpoints = worker_fabric_endpoints(profile.cloud)
    http = BearerDeployHttp(http_client, credential, deploy_scopes(profile, endpoints))
    return DeployCollaborators(
        approvals=RepositoryPlanApprovals(
            CosmosPlanApprovalRepository.from_client(cosmos, database=database)
        ),
        register=CosmosRegisterStore.from_client(
            cosmos, database=database, container=register_container
        ),
        arm=HttpArmProvisioner(http, profile),
        fabric=FabricProvisioner(http, endpoints) if endpoints is not None else None,
        observer=FabricHttpObserver(http, endpoints) if endpoints is not None else None,
    )
