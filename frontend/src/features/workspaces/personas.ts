import type { NsRole } from "../../auth/roles";

export type Persona = NsRole;

export interface WorkspaceDef {
  readonly persona: Persona;
  readonly path: string;
  readonly label: string;
  readonly description: string;
}

/** Placeholder probe until PRP-06 defines the real authorization-checked endpoints. */
export const WORKSPACE_PROBE_BASE = "/api/v1/workspaces";

export function probePath(persona: Persona): string {
  return `${WORKSPACE_PROBE_BASE}/${persona.toLowerCase()}`;
}

export const WORKSPACES: readonly WorkspaceDef[] = [
  {
    persona: "Viewer",
    path: "/workspaces/viewer",
    label: "Viewer",
    description: "Read-only views of telemetry, cost and the catalog.",
  },
  {
    persona: "Analyst",
    path: "/workspaces/analyst",
    label: "Analyst",
    description: "Exploration, recommendations and evaluation.",
  },
  {
    persona: "Steward",
    path: "/workspaces/steward",
    label: "Steward",
    description: "Catalog curation and review of proposed changes.",
  },
  {
    persona: "Admin",
    path: "/workspaces/admin",
    label: "Admin",
    description: "Deployment, connectors and policy administration.",
  },
  {
    persona: "Auditor",
    path: "/workspaces/auditor",
    label: "Auditor",
    description: "Audit trail and evidence review.",
  },
];
