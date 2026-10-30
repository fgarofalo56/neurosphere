/** Every user-visible string for gateway manage lives here so tests assert exact values. */
export const STRINGS = {
  title: "Gateways",
  description:
    "Observe mode only reads a gateway. Manage mode lets approved actions change it. The switch drafts an audited action: nothing changes until it is validated, confirmed and approved by another person.",
  navLabel: "Gateways",
  loading: "Loading...",
  domainRequired: "Choose a domain to view gateways.",
  empty: "No gateways are registered in this domain.",
  forbidden: "You do not have access to this domain",
  forbiddenDetail: "Contact your administrator if you need access",
  unavailable: "Service unavailable",
  unavailableDetail:
    "The service could not be reached. This is not an empty result. Try again in a moment.",
  retry: "Retry",
  reference: "reference",
  mode: {
    label: "Mode",
    observe: "Observe",
    manage: "Manage",
    changedBy: "Changed by",
    changedAt: "Changed at",
    neverChanged: "Never changed since registration",
    revision: "Mode revision",
  },
  preflight: {
    title: "Write-permission preflight",
    passed: "Passed",
    failed: "Failed",
    none: "No preflight has run yet. It runs when the switch to manage mode is executed.",
    checkedAt: "Checked at",
    required: "Required actions",
    missing: "Missing actions",
    noneMissing: "None missing",
    failedHelp:
      "The service identity lacks the actions listed as missing. Grant them at the gateway scope, then draft the switch again.",
  },
  switch: {
    toManage: "Draft switch to manage mode",
    toObserve: "Draft switch to observe mode",
    working: "Drafting...",
    noPermission:
      "You need the action.propose permission in this domain to draft a mode change. Another person approves it.",
    government:
      "Manage mode is disabled for Azure Government gateways until the capability matrix lists APIM v2 tiers as available there.",
    observeNote:
      "Observe mode: publish, plan, apply and unpublish actions against this gateway are refused (gateway_observe_mode).",
    drafted: "Mode change drafted",
    draftedDetail:
      "Nothing has changed yet. Validate and confirm it in the action flow; a different person approves it.",
    openApproval: "Open the approval flow",
  },
  refusals: {
    gateway_mode_unchanged: "The gateway is already in that mode.",
    gateway_manage_unavailable: "Manage mode is not available for this gateway in its cloud.",
    gateway_applying:
      "An APIM action is running in this domain (apply, rollback or unpublish). Wait for it to finish and try again.",
    gateway_observe_mode:
      "This gateway is in observe mode, so changes to it are refused. Draft a switch to manage mode first.",
    gateway_preflight_failed:
      "The write-permission preflight failed. Grant the missing actions and try again.",
    gateway_not_registered: "This gateway is not registered.",
    forbidden: "You do not have permission to draft this change",
    unavailable: "The service is unavailable. Nothing was changed. Try again.",
    generic: "The change could not be drafted",
    title: "The change was not drafted",
  },
} as const;
