import { Button, Field, Input, makeStyles, tokens } from "@fluentui/react-components";
import { useRef, useState, type ReactElement } from "react";
import { ForbiddenError, StaleVersionError, type ApiError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../design-system";
import { ChangeConfirmDialog, type ChangeDiffRow } from "../governed-change";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useStaleConfirm, useStaleDryRun } from "./explorerHooks";
import { EntityLink } from "./explorerParts";
import { EXPLORER_STRINGS } from "./explorerStrings";
import type { StaleAgentOutcomeView, StaleAgentPlanView } from "./explorerTypes";

const S = EXPLORER_STRINGS.staleAgents;

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
  },
});

function errorText(error: ApiError): string {
  if (error instanceof StaleVersionError) return S.errorStale;
  if (error instanceof ForbiddenError) return S.errorForbidden;
  return S.errorGeneric;
}

const DIFF_CAP = 20;

/** One row per candidate (capped); the plan the server re-derives is the authority. */
function confirmDiff(plan: StaleAgentPlanView): readonly ChangeDiffRow[] {
  const rows: ChangeDiffRow[] = plan.candidates.slice(0, DIFF_CAP).map((c) => ({
    field: c.agent_id,
    before: S.confirmBefore(c.last_observed),
    after: S.confirmAfter,
  }));
  const rest = plan.candidates.length - DIFF_CAP;
  if (rest > 0) rows.push({ field: "...", before: "", after: S.confirmMore(rest) });
  return rows;
}

function PlanEcho({ plan }: { readonly plan: StaleAgentPlanView }): ReactElement {
  const f = S.planFields;
  return (
    <dl data-testid="plan-echo">
      <dt>{f.id}</dt>
      <dd data-testid="plan-id">
        <code>{plan.plan_id}</code>
      </dd>
      <dt>{f.asOf}</dt>
      <dd>
        <Timestamp value={plan.as_of} />
      </dd>
      <dt>{f.window}</dt>
      <dd>{plan.window_days}</dd>
      <dt>{f.count}</dt>
      <dd data-testid="plan-count">{plan.candidates.length}</dd>
    </dl>
  );
}

function CandidatesTable({ plan }: { readonly plan: StaleAgentPlanView }): ReactElement {
  return (
    <DataTable
      label={S.planTitle}
      rows={plan.candidates}
      getRowId={(c) => c.agent_id}
      getRowProps={(c) => ({ "data-testid": "candidate-row", "data-agent": c.agent_id })}
      columns={[
        { key: "agent", header: S.table.agent, render: (c) => <EntityLink id={c.agent_id} /> },
        { key: "domain", header: S.table.domain, render: (c) => c.domain_id },
        { key: "last", header: S.table.last, render: (c) => <Timestamp value={c.last_observed} /> },
        { key: "etag", header: S.table.etag, render: (c) => <code>{c.etag}</code> },
      ]}
    />
  );
}

function OutcomeTable({ outcome }: { readonly outcome: StaleAgentOutcomeView }): ReactElement {
  return (
    <DataTable
      label={S.outcomeTitle}
      rows={outcome.items}
      getRowId={(i) => i.agent_id}
      getRowProps={(i) => ({ "data-testid": "outcome-row", "data-agent": i.agent_id })}
      columns={[
        { key: "agent", header: S.table.agent, render: (i) => <EntityLink id={i.agent_id} /> },
        {
          key: "status",
          header: S.table.status,
          render: (i) => (
            <StatusPill
              label={i.status === "marked" ? S.marked : S.failedItem}
              tone={i.status === "marked" ? "success" : "danger"}
            />
          ),
        },
        { key: "code", header: S.table.code, render: (i) => i.code ?? "" },
      ]}
    />
  );
}

export function StaleAgentsPage(): ReactElement {
  const styles = useStyles();
  const dryRun = useStaleDryRun();
  const confirm = useStaleConfirm();
  const [days, setDays] = useState("90");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);
  const n = Number(days);
  const valid = Number.isInteger(n) && n >= 1 && n <= 3650;
  const plan = dryRun.data;
  const outcome = confirm.data;
  const canConfirm = plan !== undefined && !plan.truncated && plan.candidates.length > 0;
  const forbidden = dryRun.error instanceof ForbiddenError ? dryRun.error : null;

  return (
    <PageTemplate title={S.title} description={S.description}>
      <div className={styles.stack}>
        <Panel compact>
          <div className={styles.row}>
            <Field label={S.windowDays} validationState={valid ? "none" : "error"}>
              <Input
                type="number"
                value={days}
                min={1}
                max={3650}
                onChange={(_e, d) => setDays(d.value)}
              />
            </Field>
            <Button
              appearance="primary"
              data-testid="dry-run"
              disabled={!valid || dryRun.isPending}
              onClick={() => {
                confirm.reset();
                dryRun.mutate({ windowDays: n });
              }}
            >
              {dryRun.isPending ? S.running : S.dryRun}
            </Button>
          </div>
        </Panel>
        {forbidden !== null ? (
          <ForbiddenState workspace="catalog" correlationId={forbidden.correlationId} />
        ) : dryRun.isError ? (
          <p role="alert" data-testid="dry-run-error">
            {errorText(dryRun.error)}
          </p>
        ) : null}
        {plan === undefined ? null : (
          <Panel title={S.planTitle}>
            <p>{S.nothingChanged}</p>
            <PlanEcho plan={plan} />
            {plan.truncated ? <p data-testid="plan-truncated">{S.truncated}</p> : null}
            {plan.candidates.length === 0 ? (
              <EmptyState title={S.noCandidates} testId="no-candidates" />
            ) : (
              <CandidatesTable plan={plan} />
            )}
            {outcome === undefined ? (
              <Button
                appearance="primary"
                data-testid="confirm-open"
                disabled={!canConfirm}
                onClick={(e) => {
                  triggerRef.current = e.currentTarget;
                  setOpen(true);
                }}
              >
                {S.confirm}
              </Button>
            ) : null}
          </Panel>
        )}
        {outcome === undefined ? null : (
          <Panel title={S.outcomeTitle} testId="outcome">
            <OutcomeTable outcome={outcome} />
          </Panel>
        )}
        {confirm.isError && !open ? (
          <p role="alert" data-testid="confirm-error">
            {errorText(confirm.error)}
          </p>
        ) : null}
      </div>
      <ChangeConfirmDialog
        open={open && plan !== undefined}
        title={S.confirmTitle}
        target={plan === undefined ? "" : S.confirmTarget(plan.candidates.length, plan.plan_id)}
        version={plan === undefined ? "" : S.confirmVersion(plan.window_days, plan.as_of)}
        diff={plan === undefined ? [] : confirmDiff(plan)}
        submitting={confirm.isPending}
        reasonNote={S.confirmNote}
        error={confirm.isError ? errorText(confirm.error) : null}
        triggerRef={triggerRef}
        onSubmit={() => {
          if (plan === undefined) return;
          confirm.mutate({ plan }, { onSuccess: () => setOpen(false) });
        }}
        onClose={() => {
          setOpen(false);
          confirm.reset();
        }}
      />
    </PageTemplate>
  );
}
