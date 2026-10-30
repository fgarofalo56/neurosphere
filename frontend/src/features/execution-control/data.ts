import { useQueryClient } from "@tanstack/react-query";
import { createMutationHook, createQueryHook } from "../../api/index.js";
import { EMERGENCY_DISABLE_PATH } from "./paths";

/** Mirrors EmergencyDisableView. `changed_by` is a pseudonym. */
export interface EmergencyDisableView {
  readonly disabled: boolean;
  readonly reason: string | null;
  readonly changed_by: string | null;
  readonly changed_at: string | null;
}

export interface EmergencyDisableBody {
  readonly disabled: boolean;
  readonly reason: string | null;
}

/** Same pattern as the API (actions/models.py `_REASON`); the server still validates. */
export const REASON_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

const STATE_KEY = "execution-control-state";

export const useExecutionControl = createQueryHook<Record<string, never>, EmergencyDisableView>({
  key: STATE_KEY,
  fetcher: (client, _p, signal) =>
    client.get<EmergencyDisableView>(EMERGENCY_DISABLE_PATH, undefined, signal),
});

export const useSetExecutionControl = createMutationHook<
  EmergencyDisableBody,
  EmergencyDisableView
>({
  mutate: (client, body) => client.put<EmergencyDisableView>(EMERGENCY_DISABLE_PATH, body),
});

/** Puts the PUT response into the cache and refreshes the /actions banner's own query. */
export function useApplyExecutionView(): (view: EmergencyDisableView) => void {
  const queryClient = useQueryClient();
  return (view) => {
    queryClient.setQueryData([STATE_KEY, {}], view);
    void queryClient.invalidateQueries({ queryKey: ["actions-emergency-disable"] });
  };
}
