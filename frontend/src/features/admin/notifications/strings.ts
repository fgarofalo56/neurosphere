export const NOTIFICATION_STRINGS = {
  title: "Notifications",
  description:
    "Where governance alerts go. Channels hold a Key Vault reference to the endpoint, never the endpoint or a secret. Subscriptions choose which events reach which channel.",
  tabsLabel: "Notification sections",
  tabs: { channels: "Channels", subscriptions: "Subscriptions", deliveries: "Deliveries" },
  loading: "Loading notifications",
  empty: {
    channels: "No channels yet.",
    subscriptions: "No subscriptions yet.",
    deliveries: "No deliveries match.",
  },
  secretNote:
    "Credential fields take a Key Vault secret reference (a https://<vault>.vault.azure.net/secrets/<name> URI), never a secret value.",
  secretLabel: (what: string): string =>
    `${what} (Key Vault secret reference, not the secret value)`,
  secretInvalid: "Not a Key Vault secret reference. Enter the secret's URI, not the secret itself.",
  kindReason: (kind: string, status: string, reason: string | null): string =>
    `${kind}: ${status.replace("_", " ")}${reason === null ? "" : ` (${reason})`}`,
  review: "Review change",
  cancelEdit: "Cancel",
  confirmTitle: "Confirm notification change",
  stale: "This item changed since you loaded it. Reload and review it before saving again.",
  testOk: (id: string, status: number | null): string =>
    `Test send to ${id} succeeded${status === null ? "" : ` (HTTP ${status})`}.`,
  testFailed: (id: string, reason: string | null, status: number | null): string =>
    `Test send to ${id} failed: ${reason ?? "unknown_reason"}${status === null ? "" : ` (HTTP ${status})`}.`,
} as const;
