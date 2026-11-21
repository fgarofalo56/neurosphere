import type { ReactElement } from "react";
import { Link } from "react-router";
import { ForbiddenError, createQueryHook } from "../../api/index.js";
import {
  ErrorState,
  HealthIndicator,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
} from "../../design-system";
import { AdminConsoleHome } from "../admin/shared/AdminConsoleHome";
import { ForbiddenState } from "./ForbiddenState";
import { NoDataEmptyState, useSourceStatus, type NoDataLink } from "../source-status";
import { probePath, type Persona, type WorkspaceDef } from "./personas";

/** The pages each role works in, linked from the empty state. Navigation only; the API decides access. */
const ROLE_PAGES: Readonly<Record<Persona, readonly NoDataLink[]>> = {
  Viewer: [
    { label: "Cost dashboard", href: "/dashboards/cost" },
    { label: "Map", href: "/map" },
    { label: "Catalog", href: "/catalog" },
  ],
  Analyst: [
    { label: "Recommendations", href: "/recommendations" },
    { label: "Evaluations", href: "/evaluations" },
    { label: "Quality", href: "/quality" },
  ],
  Steward: [
    { label: "Catalog", href: "/catalog" },
    { label: "Stale agents", href: "/catalog/stale-agents" },
  ],
  Admin: [],
  Auditor: [{ label: "Audit log", href: "/audit" }],
};

/**
 * The role's pages are always listed. When a source behind them is missing or has delivered
 * nothing yet, the shared source-aware empty state says so; when every available source has data
 * (or the status cannot be read) there is nothing to report and only the pages are shown.
 */
function WorkspaceBody({ def }: { readonly def: WorkspaceDef }): ReactElement {
  const { sources } = useSourceStatus();
  const links = ROLE_PAGES[def.persona];
  const needsAttention =
    sources !== undefined && sources.some((s) => s.available && s.state !== "connected");
  if (needsAttention) {
    return (
      <NoDataEmptyState
        what={`The ${def.label} workspace has no data to show yet.`}
        sources={["foundry", "apim_gateway", "billing", "azure_monitor_telemetry"]}
        extraLinks={links}
        testId="workspace-empty"
      />
    );
  }
  return (
    <ul data-testid="workspace-pages">
      {links.map((l) => (
        <li key={l.href}>
          <Link to={l.href}>{l.label}</Link>
        </li>
      ))}
    </ul>
  );
}

const useWorkspaceProbe = createQueryHook<{ path: string }, unknown>({
  key: "workspace-probe",
  fetcher: (client, params, signal) => client.get<unknown>(params.path, undefined, signal),
});

/** The probe is issued on every mount, even when navigation to this page was hidden. */
export function WorkspacePage({ def }: { readonly def: WorkspaceDef }): ReactElement {
  const query = useWorkspaceProbe({ path: probePath(def.persona) });
  const label = `${def.label} workspace`;

  if (query.isError) {
    const error = query.error;
    if (error instanceof ForbiddenError) {
      return (
        <PageTemplate title={label}>
          <ForbiddenState workspace={def.label} correlationId={error.correlationId} />
        </PageTemplate>
      );
    }
    return (
      <PageTemplate title={label}>
        <ErrorState
          title="Could not load this workspace"
          testId="error-state"
          message={
            <>
              The request failed
              {error.correlationId !== "" ? ` (reference ${error.correlationId})` : ""}. This is not
              an empty result. Try again later.
            </>
          }
        />
      </PageTemplate>
    );
  }

  if (query.isPending) {
    return (
      <PageTemplate title={label} busy>
        <LoadingState label={`Loading the ${label}`} rows={4} />
      </PageTemplate>
    );
  }

  // PRP-53: the probe above still decides; the Admin persona then gets the console landing.
  if (def.persona === "Admin") return <AdminConsoleHome title={label} />;

  return (
    <PageTemplate title={label} layout="grid">
      <Panel title="Purpose">
        <p>{def.description}</p>
        <div>
          <StatusPill label={def.persona} tone="neutral" />
        </div>
      </Panel>
      <Panel title="Service status">
        <div>
          <HealthIndicator state="ok" label="Service answered" />
        </div>
        <WorkspaceBody def={def} />
      </Panel>
    </PageTemplate>
  );
}
