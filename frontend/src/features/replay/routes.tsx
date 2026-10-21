import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";
import { ReplayPage } from "./ReplayPage";

export const REPLAY_PATH = "/replay/traces";

export const replayRoutes: RouteObject[] = [
  { path: REPLAY_PATH.replace(/^\//, ""), element: <ReplayPage /> },
];

/** Navigation is a usability aid only; the API decides access on every request. */
export function replayNavItems(): NavItem[] {
  return [{ to: REPLAY_PATH, label: "Trace replay" }];
}
