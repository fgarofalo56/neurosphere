import { Button, Field, Input, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { domainLabel, useSelectedDomain } from "../../app/domain";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
  Timestamp,
  type DataTableColumn,
  type StatusTone,
} from "../../design-system";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { ExportDialog } from "./ExportDialog";
import { timeOk, useInteraction, useInteractionList } from "./hooks";
import { EXPLORER_UNCONFIGURED, reasonOf } from "./problems";
import { RevealContentDialog } from "./RevealContentDialog";
import { STRINGS, redactionLabel } from "./strings";
import {
  DETECTED_CATEGORIES,
  EMPTY_FILTERS,
  type InteractionFilters,
  type InteractionRecord,
} from "./types";

const useStyles = makeStyles({
  section: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  heading: { margin: 0, fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  subheading: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
  },
  muted: { margin: 0, color: tokens.colorNeutralForeground2 },
  filters: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
    gap: tokens.spacingHorizontalM,
    alignItems: "end",
  },
  actions: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalS },
  facts: {
    display: "grid",
    gridTemplateColumns: "max-content 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
    "& dd": { margin: 0, overflowWrap: "anywhere" },
  },
  coverage: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXS },
  link: {
    color: tokens.colorBrandForegroundLink,
    textDecorationLine: "none",
    fontWeight: tokens.fontWeightSemibold,
    ":hover": { textDecorationLine: "underline" },
  },
});

const INTERACTION_PARAM = "interaction_id";

function redactionTone(state: InteractionRecord["redaction_state"]): StatusTone {
  if (state === "redaction_failed") return "danger";
  return state === "redacted" ? "info" : "success";
}

function totalFindings(record: InteractionRecord): number {
  return (record.findings_summary ?? []).reduce((sum, f) => sum + f.count, 0);
}

function LoadError({
  error,
  what,
}: {
  readonly error: ApiError;
  readonly what: string;
}): ReactElement {
  if (error instanceof ForbiddenError) {
    return <ForbiddenState workspace={STRINGS.title} correlationId={error.correlationId} />;
  }
  // Explorer off is a stated deployment state, not a failure: content capture is opt-in.
  if (reasonOf(error) === EXPLORER_UNCONFIGURED) {
    return (
      <div data-testid="explorer-unconfigured">
        <EmptyState
          title={STRINGS.errors.explorerUnconfiguredTitle}
          description={STRINGS.errors.explorerUnconfigured}
        />
      </div>
    );
  }
  const reference = error.correlationId !== "" ? ` (reference ${error.correlationId})` : "";
  return (
    <ErrorState
      testId="error-state"
      title={STRINGS.errors.loadFailed(what)}
      message={STRINGS.errors.generic(reference)}
    />
  );
}

function FilterForm({
  applied,
  onApply,
}: {
  readonly applied: InteractionFilters;
  readonly onApply: (next: InteractionFilters) => void;
}): ReactElement {
  const styles = useStyles();
  const [draft, setDraft] = useState<InteractionFilters>(applied);
  const [attempted, setAttempted] = useState(false);
  const F = STRINGS.filters;
  const text = (key: keyof InteractionFilters, label: string, time = false) => {
    const bad = time && attempted && !timeOk(draft[key]);
    return (
      <Field
        label={label}
        hint={time ? F.timeHint : undefined}
        validationState={bad ? "error" : "none"}
        validationMessage={bad ? F.timeInvalid : undefined}
      >
        <Input
          value={draft[key]}
          maxLength={512}
          data-testid={`filter-${key}`}
          onChange={(_e, d) => setDraft({ ...draft, [key]: d.value })}
        />
      </Field>
    );
  };
  return (
    <form
      aria-label={STRINGS.filtersHeading}
      className={styles.section}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setAttempted(true);
        if (!timeOk(draft.from) || !timeOk(draft.to)) return;
        onApply(draft);
      }}
    >
      <div className={styles.filters}>
        {text("agentId", F.agent)}
        {text("principalId", F.principal)}
        {text("toolId", F.tool)}
        {text("dataAssetId", F.dataAsset)}
        <Field label={F.category}>
          <Select
            value={draft.detectedCategory}
            data-testid="filter-detectedCategory"
            onChange={(_e, d) => setDraft({ ...draft, detectedCategory: d.value })}
          >
            <option value="">{F.any}</option>
            {DETECTED_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>
        {text("from", F.from, true)}
        {text("to", F.to, true)}
      </div>
      <div className={styles.actions}>
        <Button type="submit" appearance="primary">
          {F.apply}
        </Button>
        <Button
          onClick={() => {
            setDraft(EMPTY_FILTERS);
            onApply(EMPTY_FILTERS);
          }}
        >
          {F.clear}
        </Button>
      </div>
    </form>
  );
}

function InteractionList({
  domainId,
  filters,
}: {
  readonly domainId: string;
  readonly filters: InteractionFilters;
}): ReactElement {
  const styles = useStyles();
  const query = useInteractionList(domainId, filters);
  const [params] = useSearchParams();
  if (query.isError) return <LoadError error={query.error} what="interactions" />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="interaction-list-loading">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  const items = query.data.pages.flatMap((p) => p.items);
  const columns: readonly DataTableColumn<InteractionRecord>[] = [
    {
      key: "open",
      header: STRINGS.columns.open,
      minWidth: "220px",
      render: (r) => {
        const next = new URLSearchParams(params);
        next.set(INTERACTION_PARAM, r.interaction_id);
        return (
          <Link to={`?${next.toString()}`} className={styles.link}>
            {STRINGS.openInteraction} {r.interaction_id}
          </Link>
        );
      },
    },
    {
      key: "captured",
      header: STRINGS.columns.captured,
      render: (r) => <Timestamp value={r.captured_at} />,
    },
    {
      key: "agent",
      header: STRINGS.columns.agent,
      render: (r) => r.agent_id ?? STRINGS.notReported,
    },
    {
      key: "principal",
      header: STRINGS.columns.principal,
      render: (r) => r.principal_id ?? STRINGS.notReported,
    },
    {
      key: "findings",
      header: STRINGS.columns.findings,
      render: (r) => STRINGS.findingsCount(totalFindings(r)),
    },
    {
      key: "redaction",
      header: STRINGS.columns.redaction,
      render: (r) => (
        <StatusPill
          label={redactionLabel(r.redaction_state)}
          tone={redactionTone(r.redaction_state)}
        />
      ),
    },
  ];
  return (
    <section className={styles.section} aria-labelledby="interaction-list-heading">
      <h2 id="interaction-list-heading" className={styles.heading}>
        {STRINGS.listHeading}
      </h2>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={STRINGS.noInteractions} />
        </div>
      ) : (
        <DataTable
          label={STRINGS.listHeading}
          columns={columns}
          rows={items}
          getRowId={(r) => r.interaction_id}
          getRowProps={() => ({ "data-testid": "interaction-row" })}
        />
      )}
      {query.hasNextPage ? (
        <div>
          <Button onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>
            {STRINGS.loadMore}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

export function InteractionDetail({
  record,
  domainId,
}: {
  readonly record: InteractionRecord;
  readonly domainId: string;
}): ReactElement {
  const styles = useStyles();
  const D = STRINGS.detail;
  const findings = record.findings_summary ?? [];
  const model = record.model;
  const modelText =
    model === null || model === undefined
      ? STRINGS.notReported
      : [model.provider, model.model_name, model.model_version]
          .filter((v) => v !== null)
          .join(" / ") || STRINGS.notReported;
  const assets = record.data_asset_ids ?? [];
  const holds = record.legal_hold_ids ?? [];
  return (
    <section
      className={styles.section}
      aria-labelledby="interaction-detail-heading"
      data-testid="interaction-detail"
    >
      <h2 id="interaction-detail-heading" className={styles.heading}>
        {D.heading(record.interaction_id)}
      </h2>
      <dl className={styles.facts}>
        <dt>{D.captured}</dt>
        <dd>
          <Timestamp value={record.captured_at} />
        </dd>
        <dt>{D.occurred}</dt>
        <dd>
          <Timestamp value={record.occurred_at} />
        </dd>
        <dt>{D.source}</dt>
        <dd>{record.capture_source}</dd>
        <dt>{D.agent}</dt>
        <dd>{record.agent_id ?? STRINGS.notReported}</dd>
        <dt>{D.tool}</dt>
        <dd>{record.tool_id ?? STRINGS.notReported}</dd>
        <dt>{D.principal}</dt>
        <dd>{record.principal_id ?? STRINGS.notReported}</dd>
        <dt>{D.model}</dt>
        <dd>{modelText}</dd>
        <dt>{D.dataAssets}</dt>
        <dd>{assets.length === 0 ? STRINGS.none : assets.join(", ")}</dd>
        <dt>{D.parts}</dt>
        <dd data-testid="detail-parts">
          {record.parts.length === 0
            ? STRINGS.none
            : record.parts
                .map(
                  (p) =>
                    `${p.part} (${p.char_count} characters${p.truncated ? ", truncated" : ""})`,
                )
                .join(", ")}
        </dd>
        <dt>{D.redaction}</dt>
        <dd data-testid="detail-redaction">
          <StatusPill
            label={redactionLabel(record.redaction_state)}
            tone={redactionTone(record.redaction_state)}
          />
        </dd>
        <dt>{D.policy}</dt>
        <dd>
          {record.capture_policy_id} v{record.capture_policy_version}
        </dd>
        <dt>{D.expires}</dt>
        <dd>
          <Timestamp value={record.expires_at} />
        </dd>
        <dt>{D.legalHolds}</dt>
        <dd>{holds.length === 0 ? STRINGS.none : holds.join(", ")}</dd>
      </dl>
      <h3 className={styles.subheading}>{D.findingsHeading}</h3>
      <div className={styles.coverage}>
        <span data-testid="coverage-label">
          <StatusPill label={D.coverageLabel} tone="neutral" />
        </span>
        <p className={styles.muted}>{D.coverageNote}</p>
      </div>
      {findings.length === 0 ? (
        <p className={styles.muted} data-testid="no-findings">
          {D.noFindings}
        </p>
      ) : (
        <ul aria-label={D.findingsHeading} data-testid="findings-list">
          {findings.map((f) => (
            <li key={`${f.category}-${f.action}`}>
              {f.category}: {f.count} ({D.findingAction[f.action]})
            </li>
          ))}
        </ul>
      )}
      <div className={styles.actions}>
        <RevealContentDialog
          key={record.interaction_id}
          domainId={domainId}
          interactionId={record.interaction_id}
          hasContent={record.content_ref !== null}
        />
      </div>
      {record.content_ref === null ? (
        <p className={styles.muted} data-testid="no-content">
          {D.noContent}
        </p>
      ) : null}
    </section>
  );
}

function DetailSection({
  domainId,
  interactionId,
}: {
  readonly domainId: string;
  readonly interactionId: string;
}): ReactElement {
  const query = useInteraction({ domainId, interactionId });
  if (query.isError) return <LoadError error={query.error} what="the interaction" />;
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="interaction-detail-loading">
        <LoadingState label={STRINGS.loading} rows={4} />
      </div>
    );
  }
  return <InteractionDetail record={query.data} domainId={domainId} />;
}

function DomainPicker(): ReactElement | null {
  const { domainId, domains, setDomain } = useSelectedDomain();
  if (domains.length === 0) return null;
  return (
    <Field label={STRINGS.domainLabel}>
      <Select value={domainId} onChange={(_e, d) => setDomain(d.value)} data-testid="domain-picker">
        {domains.some((d) => d.domain_id === domainId) ? null : (
          <option value={domainId}>{domainId}</option>
        )}
        {domains.map((d) => (
          <option key={d.domain_id} value={d.domain_id}>
            {domainLabel(d)}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function InteractionsPage(): ReactElement {
  const styles = useStyles();
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const [filters, setFilters] = useState<InteractionFilters>(EMPTY_FILTERS);
  const interactionId = params.get(INTERACTION_PARAM) ?? "";
  return (
    <PageTemplate title={STRINGS.title} description={STRINGS.description}>
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <>
          <section className={styles.section} aria-labelledby="interaction-filters-heading">
            <h2 id="interaction-filters-heading" className={styles.heading}>
              {STRINGS.filtersHeading}
            </h2>
            <DomainPicker />
            <FilterForm key={domainId} applied={filters} onApply={setFilters} />
            <div className={styles.actions}>
              <ExportDialog domainId={domainId} filters={filters} />
            </div>
          </section>
          <InteractionList domainId={domainId} filters={filters} />
          {interactionId !== "" ? (
            <DetailSection domainId={domainId} interactionId={interactionId} />
          ) : null}
        </>
      )}
    </PageTemplate>
  );
}
