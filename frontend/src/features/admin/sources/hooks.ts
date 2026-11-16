import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useCallback } from "react";
import type { ApiError } from "../../../api/index.js";
import {
  adminRequest,
  useAdminGet,
  useAdminTransport,
  useEtagMutation,
  type AdminResponse,
} from "../shared/transport";
import { connectorPaths, existingPaths, producerPaths } from "./apiPaths";
import type {
  ConnectorConfigBody,
  ConnectorPage,
  ConnectorView,
  MeDomains,
  ProducerPage,
  ProducerSecretIssued,
  ProducerView,
} from "./types";

export const PRODUCERS_KEY = "admin-producers";
export const CONNECTORS_KEY = "admin-connectors";
export const ME_DOMAINS_KEY = "admin-me-domains";

export function useProducers() {
  return useAdminGet<ProducerPage>(PRODUCERS_KEY, {
    path: producerPaths.list(),
    query: { limit: 200 },
  });
}

/** Reads one producer to get the ETag its next change is bound to. */
export function useReadProducer() {
  return useEtagMutation<string, ProducerView>((id) => ({
    method: "GET",
    path: producerPaths.one(id),
  }));
}

export interface CreateProducerVars {
  readonly producerId: string;
  readonly cloud: "commercial" | "government";
  readonly sources: Readonly<Record<string, string>>;
}

/**
 * Create and rotate return the secret exactly once. These mutations never keep it: `gcTime: 0`
 * drops the mutation from the cache as soon as nothing observes it, and the page calls `reset()`
 * right after it has moved the value into local state that it clears on close and on unmount.
 */
export function useCreateProducer(): UseMutationResult<
  AdminResponse<ProducerSecretIssued>,
  ApiError,
  CreateProducerVars
> {
  const transport = useAdminTransport();
  return useMutation<AdminResponse<ProducerSecretIssued>, ApiError, CreateProducerVars>({
    gcTime: 0,
    mutationFn: (v) =>
      adminRequest<ProducerSecretIssued>(transport, {
        method: "POST",
        path: producerPaths.list(),
        body: { producer_id: v.producerId, cloud: v.cloud, sources: v.sources },
      }),
  });
}

export interface ProducerChangeVars {
  readonly producerId: string;
  readonly etag: string | undefined;
}

export function useRotateProducer(): UseMutationResult<
  AdminResponse<ProducerSecretIssued>,
  ApiError,
  ProducerChangeVars
> {
  const transport = useAdminTransport();
  return useMutation<AdminResponse<ProducerSecretIssued>, ApiError, ProducerChangeVars>({
    gcTime: 0,
    mutationFn: (v) =>
      adminRequest<ProducerSecretIssued>(transport, {
        method: "POST",
        path: producerPaths.rotate(v.producerId),
        ifMatch: v.etag,
      }),
  });
}

export function useSetProducerStatus() {
  return useEtagMutation<ProducerChangeVars & { readonly enable: boolean }, ProducerView>((v) => ({
    method: "POST",
    path: v.enable ? producerPaths.enable(v.producerId) : producerPaths.disable(v.producerId),
    ifMatch: v.etag,
  }));
}

export function useConnectors(kind: string | undefined) {
  return useAdminGet<ConnectorPage>(CONNECTORS_KEY, {
    path: connectorPaths.list(),
    query: { connector_kind: kind, include_retired: false, limit: 200 },
  });
}

export function useReadConnector() {
  return useEtagMutation<string, ConnectorView>((id) => ({
    method: "GET",
    path: connectorPaths.one(id),
  }));
}

export function useCreateConnector() {
  return useEtagMutation<ConnectorConfigBody, ConnectorView>((body) => ({
    method: "POST",
    path: connectorPaths.list(),
    body,
  }));
}

export function useReplaceConnector() {
  return useEtagMutation<
    { readonly body: ConnectorConfigBody; readonly etag: string | undefined },
    ConnectorView
  >((v) => ({
    method: "PUT",
    path: connectorPaths.one(v.body.connector_id),
    body: v.body,
    ifMatch: v.etag,
  }));
}

export type ConnectorAction = "enable" | "disable" | "retire";

export function useConnectorAction() {
  return useEtagMutation<
    {
      readonly connectorId: string;
      readonly action: ConnectorAction;
      readonly etag: string | undefined;
    },
    ConnectorView
  >((v) =>
    v.action === "retire"
      ? { method: "DELETE", path: connectorPaths.one(v.connectorId), ifMatch: v.etag }
      : {
          method: "POST",
          path:
            v.action === "enable"
              ? connectorPaths.enable(v.connectorId)
              : connectorPaths.disable(v.connectorId),
          ifMatch: v.etag,
        },
  );
}

/** The domains the caller can read, for the domain pickers. */
export function useReadableDomains() {
  return useAdminGet<MeDomains>(ME_DOMAINS_KEY, { path: existingPaths.myDomains() });
}

/** Invalidates every cached read whose key starts with `key`. */
export function useInvalidate(key: string): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(() => queryClient.invalidateQueries({ queryKey: [key] }), [queryClient, key]);
}
