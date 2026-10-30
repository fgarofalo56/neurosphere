import { Button, Link, Text, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces";
import { buildChoices, type ChoicesDraft } from "./ChoicesStep";
import { usePlan } from "./data";
import { STRINGS } from "./strings";
import type { PlanItem, PlanRequest, PlanResponse, ScanResponse } from "./types";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS, alignItems: "center" },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
});

const STATUS_TONE: Record<PlanItem["status"], StatusTone> = {
  reuse: "success",
  create: "info",
  skip: "neutral",
  needs_consent: "warning",
  disabled: "danger",
};

const CHECK_TONE: Record<string, StatusTone> = {
  pass: "success",
  fail: "danger",
  unknown: "warning",
};

function costText(item: PlanItem): string {
  const c = item.cost_implication;
  if (c.basis === "unknown") return `${c.basis}: ${STRINGS.unknown}`;
  const amount =
    c.monthly_amount === null || c.monthly_amount === undefined
      ? ""
      : ` ${c.monthly_amount} ${c.currency ?? ""}/month`;
  return `${c.basis}${amount}${c.summary === null || c.summary === undefined ? "" : `. ${c.summary}`}`;
}

/** Only https links are rendered; anything else is shown as plain text, never as a link. */
function SourceLink({ url }: { readonly url: string | null | undefined }): ReactElement | null {
  if (url === null || url === undefined || url === "") return null;
  if (!url.startsWith("https://")) return <Text>{url}</Text>;
  return (
    <Link href={url} target="_blank" rel="noopener noreferrer">
      {STRINGS.sourceLink}
    </Link>
  );
}

const COLUMNS: readonly DataTableColumn<PlanItem>[] = [
  { key: "service", header: STRINGS.columns.service, render: (i) => i.service },
  {
    key: "status",
    header: STRINGS.columns.status,
    render: (i) => <StatusPill label={i.status} tone={STATUS_TONE[i.status]} />,
  },
  {
    key: "resource",
    header: STRINGS.columns.resource,
    render: (i) => i.existing_resource_id ?? "",
  },
  {
    key: "flags",
    header: STRINGS.columns.flags,
    render: (i) => (
      <span>
        {i.shared ? <StatusPill label={STRINGS.shared} tone="warning" /> : null}
        {i.neurosphere_created ? (
          <StatusPill label={STRINGS.neurosphereCreated} tone="info" />
        ) : null}
      </span>
    ),
  },
  {
    key: "checks",
    header: STRINGS.columns.checks,
    render: (i) => (
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {i.checks.map((c) => (
          <li key={c.name}>
            <StatusPill
              label={`${c.name}: ${c.outcome}`}
              tone={CHECK_TONE[c.outcome] ?? "neutral"}
            />{" "}
            {c.reason}
          </li>
        ))}
      </ul>
    ),
  },
  { key: "cost", header: STRINGS.columns.cost, render: (i) => costText(i) },
  { key: "reason", header: STRINGS.columns.reason, render: (i) => i.disabled_reason ?? "" },
  {
    key: "source",
    header: STRINGS.columns.source,
    render: (i) => <SourceLink url={i.source_url} />,
  },
];

/** Downloads the manifest as JSON from memory. Nothing is sent anywhere. */
export function downloadManifest(manifest: unknown, deploymentId: string): void {
  const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = `${deploymentId}-manifest.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

export interface PlanStepProps {
  readonly scan: ScanResponse | null;
  readonly draft: ChoicesDraft;
}

/** Step 3. There is deliberately no apply, provision or delete control: the plan is advisory. */
export function PlanStep({ scan, draft }: PlanStepProps): ReactElement {
  const styles = useStyles();
  const mutation = usePlan();
  const result: PlanResponse | undefined = mutation.data;

  function build(): void {
    const request: PlanRequest = {
      profile: {
        cloud: draft.profile.cloud,
        regions: [draft.profile.region],
        hosting: draft.profile.hosting,
        analytics: draft.profile.analytics,
        features: [],
        allow_preview: false,
      },
      scan,
      choices: buildChoices(draft.services),
      consents: draft.consents,
    };
    mutation.mutate(request);
  }

  const error = mutation.isError ? mutation.error : null;
  return (
    <div className={styles.stack}>
      <div>
        <Button
          appearance="primary"
          onClick={build}
          disabled={mutation.isPending}
          data-testid="plan-build"
        >
          {STRINGS.planButton}
        </Button>
      </div>
      {error === null ? null : error instanceof ForbiddenError ? (
        <ForbiddenState
          workspace={STRINGS.forbiddenWorkspace}
          correlationId={error.correlationId}
        />
      ) : (
        <ErrorState
          title={STRINGS.planFailed}
          message={error.correlationId === "" ? undefined : `Reference: ${error.correlationId}.`}
          testId="plan-error"
        />
      )}
      {result === undefined ? null : (
        <section className={styles.stack} aria-label={STRINGS.planTitle} data-testid="plan-result">
          <Text>{STRINGS.planNotApplied}</Text>
          <Text>
            Plan {result.plan.plan_id}, created <Timestamp value={result.plan.created_at} />
          </Text>
          {result.plan.capability_warnings.length === 0 ? null : (
            <div data-testid="plan-warnings">
              <Text weight="semibold">{STRINGS.warningsTitle}</Text>
              <ul className={styles.list}>
                {result.plan.capability_warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {result.plan.items.length === 0 ? (
            <EmptyState title="The plan has no items" />
          ) : (
            <DataTable
              label={STRINGS.planTable}
              columns={COLUMNS}
              rows={result.plan.items}
              getRowId={(i) => `${i.kind}:${i.service}`}
              getRowProps={(i) => ({ "data-testid": "plan-row", "data-status": i.status })}
            />
          )}
          <div className={styles.row}>
            <Button
              onClick={() => downloadManifest(result.manifest, result.plan.deployment_id)}
              data-testid="manifest-download"
            >
              {STRINGS.downloadManifest}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
