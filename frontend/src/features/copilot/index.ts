import type { RouteObject } from "react-router";
import type { NavItem } from "../../app/routes";

/**
 * Placeholder from PRP-19 item 7 so the app shell can mount the copilot before the chat UI
 * exists. Item 6 replaces the contents of this module and keeps these export names, so it never
 * edits `frontend/src/app/`.
 */
export const copilotRoutes: RouteObject[] = [];

/** Navigation is a usability aid only; the API decides access on every request. */
export function copilotNavItems(): NavItem[] {
  return [];
}

/** The chat panel mounted once in the authenticated app shell. Renders nothing until item 6. */
export function CopilotDock(): null {
  return null;
}

export {
  COPILOT_API_PREFIX,
  COPILOT_CONVERSATIONS_PATH,
  conversationMessagesPath,
  conversationPath,
} from "./paths";
