import { createMutationHook, createQueryHook } from "../../api/index.js";
import { gatewayModePath, gatewaysPath } from "./paths";
import type { ActionView, GatewayList, GatewayListParams, ModeChangeVars } from "./types";

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
