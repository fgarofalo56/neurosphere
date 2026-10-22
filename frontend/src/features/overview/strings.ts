/** Every user-visible string of the overview page, so tests assert exact values. */
export const STRINGS = {
  // The home page keeps the product name as its h1 (app/shell.test.tsx and app/routes.test.tsx
  // pin it); the description says what the page is.
  title: "NeuroSphere",
  description: "Overview of the selected domain. Counts with + have more on the next page.",
  gridLabel: "Domain summary",
  loading: "Loading...",
  loadingDomains: "Loading your domains...",
  pickDomain: "Choose a domain in the header domain switcher to see its summary.",
  unknown: "unknown",
  notLoaded: "not loaded",
  forbidden: "You do not have access to this data.",
  failed: "This summary could not be loaded.",
  cost: {
    title: "Cost, last day",
    link: "Open cost dashboard",
    window: "Per currency, not summed",
  },
  review: { title: "Pending review", link: "Open review queue" },
  awaiting: {
    title: "Awaiting confirmation or approval",
    link: "Open actions",
    confirmation: "Awaiting confirmation",
    approval: "Awaiting approval",
  },
  map: { title: "Map coverage", link: "Open map", asOf: "as of" },
  reports: { title: "Recent reports", link: "Open reports" },
} as const;
