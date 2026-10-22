/**
 * Path constants for the copilot feature (placeholder from PRP-19 item 7; item 6 builds the chat
 * UI on top and keeps these names). Kept free of heavy imports so the app shell can reference
 * them without loading Fluent UI.
 *
 * Conversations are user-scoped, not domain-scoped: the API derives the owner from the token and
 * the message context is a hint that can only narrow the server-derived scope.
 */
export const COPILOT_API_PREFIX = "/api/v1/copilot";

export const COPILOT_CONVERSATIONS_PATH = `${COPILOT_API_PREFIX}/conversations`;

export function conversationPath(conversationId: string): string {
  return `${COPILOT_CONVERSATIONS_PATH}/${encodeURIComponent(conversationId)}`;
}

export function conversationMessagesPath(conversationId: string): string {
  return `${conversationPath(conversationId)}/messages`;
}
