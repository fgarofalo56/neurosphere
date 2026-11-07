import {
  Button,
  Checkbox,
  Field,
  Input,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useMemo, useState, type ReactElement } from "react";
import { ApiError, DependencyTransientError, ForbiddenError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  StatusPill,
  Timestamp,
  type DataTableColumn,
} from "../../design-system";
import type { ActionView } from "../actions/types";
import { useApplyPlan, useApprovePlan, useUninstallPreview } from "./data";
import { STRINGS } from "./strings";
import type { ApplyTarget, PlanItem, PlanResponse, PlannedResource, UninstallEntry } from "./types";
import {
  checkDeploymentId,
  checkRegion,
  checkResourceGroup,
  checkSku,
  checkSubscriptionId,
} from "./validate";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  panel: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
  },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS, alignItems: "center" },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
  mono: { fontFamily: tokens.fontFamilyMonospace, overflowWrap: "anywhere" },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

/** Stable client key so a retried click replays the same intent instead of drafting a second. */
function newKey(prefix: string): string {
  const id =
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${id}`;
}

/**
 * Maps a failed apply-route call to what the API actually said. 403 is shown as a denial (the
 * UI grants nothing), 503 `apply_not_configured` as "not enabled in this deployment", anything
 * else as a refusal with its reason code.
 */
export function ApplyError({
  error,
  title,
  testId,
}: {
  readonly error: ApiError;
  readonly title: string;
  readonly testId: string;
}): ReactElement {
  const reason = error.problem?.reason;
  const reference =
    error.correlationId === "" ? "" : ` ${STRINGS.referenceLabel(error.correlationId)}`;
  const why = reason === undefined || reason === "" ? "" : ` ${STRINGS.reasonLabel(reason)}`;
  if (error instanceof ForbiddenError) {
    return (
      <ErrorState
        tone="warning"
        title={STRINGS.forbiddenTitle}
        message={`${STRINGS.forbiddenBody}${why}${reference}`}
        testId="apply-forbidden"
      />
    );
  }
  if (error instanceof DependencyTransientError && reason === "apply_not_configured") {
    return (
      <ErrorState
        tone="warning"
        title={STRINGS.notEnabledTitle}
        message={`${STRINGS.notEnabledBody}${reference}`}
        testId="apply-not-enabled"
      />
    );
  }
  return (
    <ErrorState
      title={title}
      message={`${error.problem?.title ?? error.message}.${why}${reference}`}
      testId={testId}
    />
  );
}

/** What the executor actually did, derived from the API state, never assumed. */
export function outcomeText(view: ActionView): { text: string; applied: boolean } {
  const { state, status_reason } = view.intent;
  if (state === "succeeded" && view.execution?.verify_matched === true) {
    return { text: STRINGS.outcomeApplied, applied: true };
  }
  if (state === "failed" || state === "rolled_back" || state === "expired") {
    return { text: STRINGS.outcomeFailed(state, status_reason), applied: false };
  }
  return { text: STRINGS.outcomeNotApplied(state), applied: false };
}

const RESOURCE_COLUMNS: readonly DataTableColumn<PlannedResource>[] = [
  { key: "service", header: STRINGS.resCols.service, render: (r) => r.service },
  { key: "kind", header: STRINGS.resCols.kind, render: (r) => r.kind },
  {
    key: "disposition",
    header: STRINGS.resCols.disposition,
    render: (r) => (
      <StatusPill label={r.disposition} tone={r.disposition === "create" ? "info" : "success"} />
    ),
  },
  { key: "name", header: STRINGS.resCols.name, render: (r) => r.name },
  { key: "region", header: STRINGS.resCols.region, render: (r) => r.region },
  { key: "sku", header: STRINGS.resCols.sku, render: (r) => r.sku ?? "" },
  { key: "id", header: STRINGS.resCols.resourceId, render: (r) => r.resource_id ?? "" },
];

const ENTRY_COLUMNS: readonly DataTableColumn<UninstallEntry>[] = [
  { key: "id", header: STRINGS.entryCols.resource, render: (e) => e.resource_id },
  { key: "service", header: STRINGS.entryCols.service, render: (e) => e.service ?? "" },
  {
    key: "ownership",
    header: STRINGS.entryCols.ownership,
    render: (e) => (e.ownership === null ? "" : <StatusPill label={e.ownership} tone="info" />),
  },
  { key: "reason", header: STRINGS.entryCols.reason, render: (e) => e.reason ?? "" },
];

function ActionSummary({ view }: { readonly view: ActionView }): ReactElement {
  const styles = useStyles();
  const { intent } = view;
  const outcome = outcomeText(view);
  return (
    <div className={styles.stack}>
      <Text data-testid="apply-outcome" data-applied={String(outcome.applied)}>
        {outcome.text}
      </Text>
      <div className={styles.row}>
        <Text>
          {STRINGS.intentLabel}: <span className={styles.mono}>{intent.intent_id}</span>
        </Text>
        <StatusPill label={`${STRINGS.stateLabel}: ${intent.state}`} tone="neutral" />
        <StatusPill
          label={`${STRINGS.executionLabel}: ${view.execution?.phase ?? STRINGS.noExecution}`}
          tone="neutral"
        />
        <Text>
          {STRINGS.requiresApproval}: {view.requires_approval ? STRINGS.yes : STRINGS.no}
        </Text>
      </div>
      <Text>
        {STRINGS.targetLabel}: <span className={styles.mono}>{intent.target.canonical_id}</span>
      </Text>
      <Text>
        {STRINGS.targetVersionLabel}: <span className={styles.mono}>{intent.target_version}</span>
      </Text>
      <div data-testid="apply-diff">
        <Text weight="semibold">{STRINGS.diffTitle}</Text>
        <ul className={styles.list}>
          {intent.proposed_diff.operations.map((op) => (
            <li key={`${op.op}:${op.path}`}>
              {STRINGS.diffOp(op.op, op.path)}
              {op.value === undefined ? null : (
                <span className={styles.mono}> {JSON.stringify(op.value)}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function blockedItems(plan: PlanResponse["plan"]): readonly PlanItem[] {
  return plan.items.filter((i) => i.status === "disabled" || i.status === "needs_consent");
}

interface TargetDraft {
  subscription: string;
  group: string;
  region: string;
  sku: string;
}

function Approve({
  plan,
  domainId,
}: {
  readonly plan: PlanResponse["plan"];
  readonly domainId: string;
}): ReactElement {
  const styles = useStyles();
  const approve = useApprovePlan();
  const apply = useApplyPlan();
  const [draft, setDraft] = useState<TargetDraft>({
    subscription: "",
    group: "",
    region: plan.profile?.regions[0] ?? "",
    sku: "F2",
  });
  const [submitted, setSubmitted] = useState(false);
  const [approvedTarget, setApprovedTarget] = useState<ApplyTarget | null>(null);
  const applyKey = useMemo(() => newKey("apply"), []);

  const blocked = blockedItems(plan);
  const consentPending = plan.items.some((i) => i.status === "needs_consent");
  const errors = {
    subscription: checkSubscriptionId(draft.subscription),
    group: checkResourceGroup(draft.group),
    region: checkRegion(draft.region),
    sku: checkSku(draft.sku),
  };
  const invalid = Object.values(errors).some((e) => e !== null);
  const show = (e: string | null): string | undefined => (submitted && e !== null ? e : undefined);
  const set = (patch: Partial<TargetDraft>): void => setDraft({ ...draft, ...patch });
  const approved = approve.data;

  function runApprove(): void {
    setSubmitted(true);
    if (invalid || consentPending) return;
    const target: ApplyTarget = {
      subscription_id: draft.subscription.trim(),
      resource_group: draft.group.trim(),
      region: draft.region.trim(),
      capacity_sku: draft.sku.trim(),
    };
    approve.mutate(
      { domainId, body: { plan, target } },
      {
        onSuccess: () => setApprovedTarget(target),
      },
    );
  }

  function runApply(): void {
    if (approved === undefined) return;
    apply.mutate({
      domainId,
      body: {
        plan_id: approved.plan_id,
        plan_hash: approved.plan_hash,
        idempotency_key: applyKey,
        channel: "button",
      },
    });
  }

  const approveError = approve.isError ? approve.error : null;
  const applyError = apply.isError ? apply.error : null;
  return (
    <div className={styles.stack}>
      <section className={styles.panel} aria-label={STRINGS.planSummaryTitle}>
        <Text weight="semibold">{STRINGS.planSummaryTitle}</Text>
        <Text data-testid="apply-plan-summary">
          {STRINGS.planSummary(plan.plan_id, plan.deployment_id)}
        </Text>
        {blocked.length === 0 ? null : (
          <div data-testid="apply-blocked">
            <Text weight="semibold">{STRINGS.optionsTitle}</Text>
            <Text className={styles.muted}> {STRINGS.optionsHint}</Text>
            <ul className={styles.list}>
              {blocked.map((i) => (
                <li key={i.service} data-testid="apply-blocked-item" data-status={i.status}>
                  <StatusPill
                    label={i.status}
                    tone={i.status === "disabled" ? "danger" : "warning"}
                  />{" "}
                  {STRINGS.optionReason(
                    i.service,
                    i.disabled_reason ??
                      i.checks.find((c) => c.outcome === "fail")?.reason ??
                      STRINGS.noReason,
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className={styles.panel} aria-label={STRINGS.applyTargetTitle}>
        <Text weight="semibold">{STRINGS.applyTargetTitle}</Text>
        <Text className={styles.muted}>{STRINGS.applyTargetHint}</Text>
        <Field
          label={STRINGS.subscriptionLabel}
          required
          validationState={show(errors.subscription) === undefined ? "none" : "error"}
          validationMessage={show(errors.subscription)}
        >
          <Input value={draft.subscription} onChange={(_, d) => set({ subscription: d.value })} />
        </Field>
        <Field
          label={STRINGS.resourceGroupLabel}
          required
          validationState={show(errors.group) === undefined ? "none" : "error"}
          validationMessage={show(errors.group)}
        >
          <Input value={draft.group} onChange={(_, d) => set({ group: d.value })} />
        </Field>
        <Field
          label={STRINGS.regionLabel}
          required
          validationState={show(errors.region) === undefined ? "none" : "error"}
          validationMessage={show(errors.region)}
        >
          <Input value={draft.region} onChange={(_, d) => set({ region: d.value })} />
        </Field>
        <Field
          label={STRINGS.capacitySkuLabel}
          validationState={show(errors.sku) === undefined ? "none" : "error"}
          validationMessage={show(errors.sku)}
        >
          <Input value={draft.sku} onChange={(_, d) => set({ sku: d.value })} />
        </Field>
        <div className={styles.row}>
          <Button
            appearance="primary"
            onClick={runApprove}
            disabled={approve.isPending || consentPending}
            data-testid="approve-run"
          >
            {STRINGS.approveButton}
          </Button>
          {consentPending ? (
            <Text data-testid="approve-blocked">{STRINGS.approveBlocked}</Text>
          ) : null}
        </div>
        {approveError === null ? null : (
          <ApplyError error={approveError} title={STRINGS.approveFailed} testId="approve-error" />
        )}
      </section>

      <section
        className={styles.panel}
        aria-label={STRINGS.approvedTitle}
        data-testid="approval-state"
      >
        <Text weight="semibold">{STRINGS.approvedTitle}</Text>
        {approved === undefined ? (
          <StatusPill label={STRINGS.notApproved} tone="neutral" testId="approval-status" />
        ) : (
          <>
            <StatusPill label={STRINGS.approvedStatus} tone="success" testId="approval-status" />
            <Text>{STRINGS.approvedNote}</Text>
            <Text>
              {STRINGS.planHash}: <span className={styles.mono}>{approved.plan_hash}</span>
            </Text>
            <Text>
              {STRINGS.resourcesDigest}:{" "}
              <span className={styles.mono}>{approved.resources_digest}</span>
            </Text>
            <Text>
              {STRINGS.deploymentIdLabel}: {approved.deployment_id}. {STRINGS.approvedCloud}:{" "}
              {approved.cloud}
            </Text>
            {approvedTarget === null ? null : (
              <Text data-testid="approved-target">
                {STRINGS.targetLabel}: {approvedTarget.subscription_id} /{" "}
                {approvedTarget.resource_group} / {approvedTarget.region} /{" "}
                {approvedTarget.capacity_sku}
              </Text>
            )}
            <Text>
              {STRINGS.approvedAt} <Timestamp value={approved.approved_at} />. {STRINGS.expiresAt}{" "}
              <Timestamp value={approved.expires_at} />
            </Text>
            <DataTable
              label={STRINGS.applyResourcesTable}
              columns={RESOURCE_COLUMNS}
              rows={approved.resources}
              getRowId={(r) => `${r.kind}:${r.name}`}
              getRowProps={(r) => ({
                "data-testid": "approved-resource",
                "data-disposition": r.disposition,
              })}
            />
          </>
        )}
      </section>

      <section className={styles.panel} aria-label={STRINGS.applyDraftTitle}>
        <Text className={styles.muted}>{STRINGS.applyHint}</Text>
        <div>
          <Button
            onClick={runApply}
            disabled={approved === undefined || apply.isPending}
            data-testid="apply-run"
          >
            {STRINGS.applyButton}
          </Button>
        </div>
        {applyError === null ? null : (
          <ApplyError error={applyError} title={STRINGS.applyFailed} testId="apply-error" />
        )}
        {apply.data === undefined ? null : (
          <div className={styles.stack} data-testid="apply-result">
            <Text weight="semibold">{STRINGS.applyDraftTitle}</Text>
            <Text>
              {STRINGS.planHash}: <span className={styles.mono}>{apply.data.plan_hash}</span>
            </Text>
            <ActionSummary view={apply.data.action} />
          </div>
        )}
      </section>
    </div>
  );
}

function Uninstall({
  domainId,
  defaultDeployment,
}: {
  readonly domainId: string;
  readonly defaultDeployment: string;
}): ReactElement {
  const styles = useStyles();
  const preview = useUninstallPreview();
  const [deployment, setDeployment] = useState(defaultDeployment);
  const [verifyLive, setVerifyLive] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const error = checkDeploymentId(deployment);
  const key = useMemo(() => newKey("uninstall"), []);

  function run(): void {
    setSubmitted(true);
    if (error !== null) return;
    preview.mutate({
      domainId,
      body: {
        deployment_id: deployment.trim(),
        idempotency_key: key,
        channel: "button",
        verify_live: verifyLive,
      },
    });
  }

  const failure = preview.isError ? preview.error : null;
  const result = preview.data;
  return (
    <section className={styles.panel} aria-label={STRINGS.uninstallTitle} data-testid="uninstall">
      <Text weight="semibold">{STRINGS.uninstallTitle}</Text>
      <Text className={styles.muted}>{STRINGS.uninstallHint}</Text>
      <Field
        label={STRINGS.uninstallDeploymentLabel}
        validationState={submitted && error !== null ? "error" : "none"}
        validationMessage={submitted && error !== null ? error : undefined}
      >
        <Input value={deployment} onChange={(_, d) => setDeployment(d.value)} />
      </Field>
      <Checkbox
        checked={verifyLive}
        onChange={(_, d) => setVerifyLive(d.checked === true)}
        label={STRINGS.verifyLiveLabel}
      />
      <div>
        <Button onClick={run} disabled={preview.isPending} data-testid="uninstall-run">
          {STRINGS.uninstallButton}
        </Button>
      </div>
      {failure === null ? null : (
        <ApplyError error={failure} title={STRINGS.uninstallFailed} testId="uninstall-error" />
      )}
      {result === undefined ? null : (
        <div className={styles.stack} data-testid="uninstall-result">
          <StatusPill label={STRINGS.uninstallDryRun} tone="info" />
          <Text>
            {STRINGS.deploymentIdLabel}: {result.deployment_id}. {STRINGS.registerDigest}:{" "}
            <span className={styles.mono}>{result.register_digest}</span>
          </Text>
          <Text weight="semibold">{STRINGS.removableTitle}</Text>
          {result.removable.length === 0 ? (
            <EmptyState title={STRINGS.noneRemovable} testId="uninstall-none-removable" />
          ) : (
            <DataTable
              label={STRINGS.removableTitle}
              columns={ENTRY_COLUMNS}
              rows={result.removable}
              getRowId={(e) => e.resource_id}
              getRowProps={() => ({ "data-testid": "uninstall-removable" })}
            />
          )}
          <Text weight="semibold">{STRINGS.untouchedTitle}</Text>
          {result.untouched.length === 0 ? (
            <EmptyState title={STRINGS.noneUntouched} testId="uninstall-none-untouched" />
          ) : (
            <DataTable
              label={STRINGS.untouchedTitle}
              columns={ENTRY_COLUMNS}
              rows={result.untouched}
              getRowId={(e) => e.resource_id}
              getRowProps={(e) => ({
                "data-testid": "uninstall-untouched",
                "data-ownership": e.ownership ?? "",
              })}
            />
          )}
          <ActionSummary view={result.action} />
        </div>
      )}
    </section>
  );
}

export interface ApplyStepProps {
  readonly plan: PlanResponse | null;
  readonly domainId: string;
}

/**
 * Step 4. Approve the exact plan and target, draft the apply intent, preview an uninstall. Every
 * call goes to the API, which authorizes `config.manage` on the domain and fails closed; this
 * page never changes Azure, never shows "applied" unless the executor's state says so, and has
 * no delete control.
 */
export function ApplyStep({ plan, domainId }: ApplyStepProps): ReactElement {
  const styles = useStyles();
  if (domainId === "") {
    return (
      <div data-testid="apply-domain-required">
        <EmptyState title={STRINGS.applyNeedDomain} />
      </div>
    );
  }
  return (
    <div className={styles.stack}>
      {plan === null ? (
        <div data-testid="apply-plan-required">
          <EmptyState title={STRINGS.applyNeedPlan} />
        </div>
      ) : (
        <Approve key={plan.plan.plan_id} plan={plan.plan} domainId={domainId} />
      )}
      <Uninstall
        key={domainId}
        domainId={domainId}
        defaultDeployment={plan === null ? "" : plan.plan.deployment_id}
      />
    </div>
  );
}
