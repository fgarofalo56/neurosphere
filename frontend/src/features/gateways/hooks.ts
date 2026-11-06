import { createMutationHook, createQueryHook } from "../../api/index.js";
import { gatewayInventoryPath, gatewayModePath, gatewayPath, gatewaysPath } from "./paths";
import type {
  ActionView,
  GatewayDetail,
  GatewayInventory,
  GatewayList,
  GatewayListParams,
  GatewayRef,
  ModeChangeVars,
} from "./types";

export const useGatewayDetail = createQueryHook<GatewayRef, GatewayDetail>({
  key: "gateway-detail",
  fetcher: (client, p, signal) =>
    client.get<GatewayDetail>(gatewayPath(p.domainId, p.gatewayId), undefined, signal),
});

export const useGatewayInventory = createQueryHook<GatewayRef, GatewayInventory>({
  key: "gateway-inventory",
  fetcher: (client, p, signal) =>
    client.get<GatewayInventory>(gatewayInventoryPath(p.domainId, p.gatewayId), undefined, signal),
});

export const useGateways = createQueryHook<GatewayListParams, GatewayList>({
  key: "gateways-list",
  fetcher: (client, p, signal) =>
    client.get<GatewayList>(gatewaysPath(p.domainId), undefined, signal),
});

/**
 * Drafts a `gateway_mode_change` action intent. It never flips the mode: the executor does that
 * after validate, confirmation and (maker-checker) approval, through the normal action flow.
 */
export const useDraftModeChange = createMutationHook<ModeChangeVars, ActionView>({
  mutate: (client, v) =>
    client.post<ActionView>(gatewayModePath(v.domainId, v.gatewayId), v.request),
});
