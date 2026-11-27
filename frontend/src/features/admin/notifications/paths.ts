/**
 * Path constants for the notification channels admin page (PRP-107 item 7). Kept free of heavy
 * imports so the areas list and the route table can reference them without loading Fluent UI.
 *
 * API (all need customer-level `config.manage`), base `/api/v1/admin/notifications`:
 * - GET /channel-kinds
 * - GET|POST /channels, GET|PUT|DELETE /channels/{id} (PUT and DELETE need If-Match)
 * - POST /channels/{id}/test
 * - GET|POST /subscriptions, GET|PUT|DELETE /subscriptions/{id}
 * - GET /deliveries?status&channel_id&limit
 */
export const ADMIN_NOTIFICATIONS_ROUTE = "admin/notifications";
export const NOTIFICATIONS_API = "/api/v1/admin/notifications";

export const notificationPaths = {
  kinds: (): string => `${NOTIFICATIONS_API}/channel-kinds`,
  channels: (): string => `${NOTIFICATIONS_API}/channels`,
  channel: (id: string): string => `${NOTIFICATIONS_API}/channels/${encodeURIComponent(id)}`,
  channelTest: (id: string): string =>
    `${NOTIFICATIONS_API}/channels/${encodeURIComponent(id)}/test`,
  subscriptions: (): string => `${NOTIFICATIONS_API}/subscriptions`,
  subscription: (id: string): string =>
    `${NOTIFICATIONS_API}/subscriptions/${encodeURIComponent(id)}`,
  deliveries: (): string => `${NOTIFICATIONS_API}/deliveries`,
};
