import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";

/**
 * The copilot is a dock mounted once in the app shell (`CopilotDock`), not a page, so it adds no
 * routes. The names stay exported because the app shell registers them.
 */
export const copilotRoutes: RouteObject[] = [];

/** Navigation is a usability aid only; the API decides access on every request. */
export function copilotNavItems(): NavItem[] {
  return [];
}

export { CopilotDock } from "./CopilotDock";
export { CopilotTransportProvider, useCopilotTransport } from "./transport";
export { setCopilotSelection, useCopilotSelection } from "./selection";
export { buildMessageContext } from "./requestContext";
export {
  COPILOT_API_PREFIX,
  COPILOT_CONVERSATIONS_PATH,
  conversationMessagesPath,
  conversationPath,
} from "./paths";
export type * from "./types";
