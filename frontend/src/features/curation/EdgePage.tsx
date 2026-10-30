import { useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Field,
  Input,
  Tab,
  TabList,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useRef, useState, type ReactElement, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { ForbiddenError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
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
import { ChangeConfirmDialog, type ChangeConfirmSubmit } from "../governed-change";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import {
  decisionDiff,
  decisionErrorMessage,
  expiryToTimestamp,
  isFuture,
  isStale,
  needsExpiry,
  useDecide,
  useEdge,
  useObservations,
  useOverrides,
} from "./data";
import { STRINGS } from "./strings";
import type {
  Decision,
  DecisionBody,
  EdgeObservation,
  EdgeOverrideRecord,
  PresentedEdge,
} from "./types";

const CURATE_PERMISSION = "catalog.curate";
const DECISIONS: readonly Decision[] = ["accept", "reject", "override", "lock", "unlock"];
type TabId = "summary" | "history" | "observations";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  list: {
    display: "grid",
    gridTemplateColumns: "minmax(10rem, max-content) 1fr",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
    margin: 0,
  },
  term: { fontWeight: tokens.fontWeightSemibold, color: tokens.colorNeutralForeground2 },
  value: { margin: 0, overflowWrap: "anywhere", minWidth: 0 },
  ids: { margin: 0, paddingInlineStart: tokens.spacingHorizontalL },
  actions: { display: "flex", flexWrap: "wrap", columnGap: tokens.spacingHorizontalS },
  muted: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

function statusTone(status: PresentedEdge["status"]): StatusTone {
  return status === "curated" ? "success" : status === "inferred" ? "warning" : "info";
}

function DetailList({
  rows,
}: {
  readonly rows: readonly { readonly term: string; readonly value: ReactNode }[];
}): ReactElement {
  const styles = useStyles();
  return (
    <dl className={styles.list}>
      {rows.map((row) => (
        <div key={row.term} style={{ display: "contents" }}>
          <dt className={styles.term}>{row.term}</dt>
          <dd className={styles.value}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function IdList({
  ids,
  testId,
}: {
  readonly ids: readonly string[];
  readonly testId: string;
}): ReactElement {
  const styles = useStyles();
  if (ids.length === 0) return <span>{STRINGS.summary.none}</span>;
  return (
    <ul className={styles.ids} data-testid={testId}>
      {ids.map((id) => (
        <li key={id}>
          <code>{id}</code>
        </li>
      ))}
    </ul>
  );
}

/** Evidence ids are listed read-only. Nothing here can remove one. */
function EdgeSummary({
  edge,
  version,
}: {
  readonly edge: PresentedEdge;
  readonly version: number | string | null;
}): ReactElement {
  const styles = useStyles();
  const s = STRINGS.summary;
  const lock = edge.lock;
  const curation = edge.curation;
  const provenance = edge.provenance;
  return (
    <div className={styles.stack} data-testid="edge-summary">
      <DetailList
        rows={[
          { term: s.edge, value: <code data-testid="edge-id">{edge.edge_id}</code> },
          { term: s.relation, value: edge.relation_type },
          { term: s.source, value: <code>{edge.source_id}</code> },
          { term: s.target, value: <code>{edge.target_id}</code> },
          { term: s.domain, value: <code>{edge.domain_id}</code> },
          {
            term: s.status,
            value: (
              <StatusPill label={edge.status} tone={statusTone(edge.status)} testId="edge-status" />
            ),
          },
          {
            term: s.confidence,
            value: <span data-testid="edge-confidence">{edge.confidence}</span>,
          },
          {
            term: s.validity,
            value: (
              <span>
                {s.validFrom} <Timestamp value={edge.validity.valid_from} />, {s.validTo}{" "}
                {edge.validity.valid_to === null || edge.validity.valid_to === undefined ? (
                  s.openEnded
                ) : (
                  <Timestamp value={edge.validity.valid_to} />
                )}
              </span>
            ),
          },
          {
            term: s.lock,
            value: lock.locked ? (
              <span data-testid="edge-lock">
                {s.locked}, {s.lockExpiry} <Timestamp value={lock.expiry ?? null} />
                {lock.reason === null || lock.reason === undefined
                  ? ""
                  : `; ${s.lockReason}: ${lock.reason}`}
                {edge.pinned ? ` (${s.pinned})` : ""}
              </span>
            ) : (
              <span data-testid="edge-lock">{s.unlocked}</span>
            ),
          },
          { term: s.visibility, value: edge.hidden ? s.hidden : s.shown },
          {
            term: s.provenance,
            value:
              provenance === null || provenance === undefined
                ? s.none
                : `${provenance.method} (${provenance.source_id})`,
          },
          {
            term: s.curation,
            value:
              curation === null || curation === undefined ? (
                s.none
              ) : (
                <span>
                  {curation.decision}: {curation.reason} (<Timestamp value={curation.decided_at} />)
                </span>
              ),
          },
          { term: s.firstObserved, value: <Timestamp value={edge.first_observed} /> },
          { term: s.lastObserved, value: <Timestamp value={edge.last_observed} /> },
          {
            term: s.version,
            value:
              version === null ? (
                STRINGS.decide.noVersion
              ) : (
                <span data-testid="edge-version">{version}</span>
              ),
          },
          { term: s.evidence, value: <IdList ids={edge.evidence_ids} testId="evidence-ids" /> },
          {
            term: s.securityEvidence,
            value: (
              <>
                <IdList ids={edge.security_evidence_ids} testId="security-evidence-ids" />
                <Text className={styles.muted}>{s.securityNote}</Text>
              </>
            ),
          },
        ]}
      />
    </div>
  );
}

function HistoryTable({ rows }: { readonly rows: readonly EdgeOverrideRecord[] }): ReactElement {
  const h = STRINGS.history;
  if (rows.length === 0) return <EmptyState title={h.empty} testId="history-empty" />;
  const columns: DataTableColumn<EdgeOverrideRecord>[] = [
    { key: "decision", header: h.decision, render: (r) => r.decision },
    { key: "reason", header: h.reason, render: (r) => r.reason },
    { key: "decided", header: h.decidedAt, render: (r) => <Timestamp value={r.decided_at} /> },
    { key: "actor", header: h.actor, render: (r) => <code>{r.actor}</code> },
    {
      key: "lock",
      header: h.lock,
      render: (r) =>
        r.lock?.expiry === null || r.lock?.expiry === undefined ? (
          "-"
        ) : (
          <Timestamp value={r.lock.expiry} />
        ),
    },
    {
      key: "confidence",
      header: h.confidence,
      render: (r) =>
        r.set_confidence === null || r.set_confidence === undefined ? "-" : r.set_confidence,
    },
  ];
  return <DataTable label={h.label} columns={columns} rows={rows} getRowId={(r) => r.id} />;
}

function ObservationsSection({
  edgeId,
  active,
}: {
  readonly edgeId: string;
  readonly active: boolean;
}): ReactElement {
  const o = STRINGS.observations;
  const styles = useStyles();
  const query = useObservations(edgeId, active);
  if (query.isPending) return <LoadingState label={o.label} rows={2} />;
  if (query.isError) {
    return query.error instanceof ForbiddenError ? (
      <ErrorState tone="warning" title={o.needsAccess} testId="observations-forbidden" />
    ) : (
      <ErrorState title={o.failed} onRetry={() => void query.refetch()} />
    );
  }
  const items: EdgeObservation[] = query.data.pages.flatMap((p) => [...p.items]);
  const columns: DataTableColumn<EdgeObservation>[] = [
    { key: "at", header: o.observedAt, render: (r) => <Timestamp value={r.observed_at} /> },
    { key: "confidence", header: o.confidence, render: (r) => r.confidence },
    { key: "method", header: o.method, render: (r) => r.provenance.method },
    { key: "source", header: o.source, render: (r) => r.provenance.source_id },
    {
      key: "evidence",
      header: o.evidence,
      render: (r) => <IdList ids={r.evidence_ids} testId={`obs-evidence-${r.id}`} />,
    },
    {
      key: "security",
      header: o.securityEvidence,
      render: (r) => <IdList ids={r.security_evidence_ids} testId={`obs-security-${r.id}`} />,
    },
  ];
  return (
    <div className={styles.stack} data-testid="observations">
      <Text className={styles.muted}>{o.kept}</Text>
      {items.length === 0 ? (
        <EmptyState title={o.empty} />
      ) : (
        <DataTable label={o.label} columns={columns} rows={items} getRowId={(r) => r.id} />
      )}
      {query.hasNextPage ? (
        <div>
          <Button onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>
            {o.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function parseConfidence(text: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : "invalid";
}

function EdgeBody({ edgeId }: { readonly edgeId: string }): ReactElement {
  const styles = useStyles();
  const queryClient = useQueryClient();
  const { domainId, domains } = useSelectedDomain();
  const edgeQuery = useEdge({ domain: domainId, edgeId }, domainId !== "");
  const overridesQuery = useOverrides({ edgeId });
  const decide = useDecide();
  const [tab, setTab] = useState<TabId>("summary");
  const [pending, setPending] = useState<Decision | null>(null);
  const [confidenceText, setConfidenceText] = useState("");
  const [dialogError, setDialogError] = useState<ReactNode>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const selected = domains.find((d) => d.domain_id === domainId);
  const canCurate = selected?.permissions.includes(CURATE_PERMISSION) ?? false;

  if (edgeQuery.isPending) return <LoadingState label={STRINGS.loading} rows={4} />;
  if (edgeQuery.isError) {
    const error = edgeQuery.error;
    if (error instanceof ForbiddenError) {
      return <ForbiddenState workspace="relationship" correlationId={error.correlationId} />;
    }
    return (
      <ErrorState
        title={STRINGS.notLoaded}
        message={error.status === 404 ? STRINGS.notFound : undefined}
        onRetry={() => void edgeQuery.refetch()}
      />
    );
  }
  const edge = edgeQuery.data.edge;
  const rawVersion = edgeQuery.data.edge_version;
  const rawEtag = edgeQuery.data.edge_etag;
  const edgeVersion: number | string | null =
    rawVersion === undefined || rawVersion === null || rawVersion === "" ? null : rawVersion;
  const edgeEtag: string | null = typeof rawEtag === "string" && rawEtag !== "" ? rawEtag : null;
  const confidenceValue = parseConfidence(confidenceText);
  const bound = edgeVersion !== null && edgeEtag !== null;

  const reload = (): void => {
    void edgeQuery.refetch();
    void overridesQuery.refetch();
    void queryClient.invalidateQueries({ queryKey: ["curation-observations", edgeId] });
  };

  const close = (): void => {
    setPending(null);
    setDialogError(null);
    decide.reset();
  };

  const submit = (value: ChangeConfirmSubmit): void => {
    if (pending === null || edgeVersion === null || edgeEtag === null || domainId === "") return;
    let lockExpiry: string | undefined;
    if (needsExpiry(pending)) {
      const stamp = value.expiry === null ? null : expiryToTimestamp(value.expiry);
      if (stamp === null) {
        setDialogError(STRINGS.decide.expiryInvalid);
        return;
      }
      if (!isFuture(stamp)) {
        setDialogError(STRINGS.decide.expiryPast);
        return;
      }
      lockExpiry = stamp;
    }
    const body: DecisionBody = {
      decision: pending,
      reason: value.reason,
      expected_edge_version: edgeVersion,
      expected_edge_etag: edgeEtag,
      ...(lockExpiry === undefined ? {} : { lock_expiry: lockExpiry }),
      ...(needsExpiry(pending) && typeof confidenceValue === "number"
        ? { set_confidence: confidenceValue }
        : {}),
    };
    setDialogError(null);
    decide.mutate(
      { domain: domainId, edgeId, body },
      {
        onSuccess: () => {
          setPending(null);
          setNotice(STRINGS.decide.done);
          reload();
        },
        onError: (error) => {
          const message = decisionErrorMessage(error);
          setDialogError(
            <div className={styles.stack}>
              <span data-testid="decision-error">{message}</span>
              {isStale(error) ? (
                <div>
                  <Button
                    onClick={() => {
                      close();
                      reload();
                    }}
                  >
                    {STRINGS.decide.reload}
                  </Button>
                </div>
              ) : null}
              {error instanceof ForbiddenError ? (
                <span className={styles.muted}>
                  {STRINGS.decide.reference}: {error.correlationId}
                </span>
              ) : null}
            </div>,
          );
        },
      },
    );
  };

  const previewConfidence = typeof confidenceValue === "number" ? confidenceValue : null;
  const visible = DECISIONS.filter((d) =>
    d === "unlock" ? edge.lock.locked : d === "lock" ? !edge.lock.locked : true,
  );

  return (
    <div className={styles.stack}>
      <TabList
        aria-label={STRINGS.tabs.label}
        selectedValue={tab}
        onTabSelect={(_e, data) => setTab(data.value as TabId)}
      >
        <Tab value="summary">{STRINGS.tabs.summary}</Tab>
        <Tab value="history">{STRINGS.tabs.history}</Tab>
        <Tab value="observations">{STRINGS.tabs.observations}</Tab>
      </TabList>

      {tab === "summary" ? <EdgeSummary edge={edge} version={edgeVersion} /> : null}
      {tab === "history" ? (
        overridesQuery.isPending ? (
          <LoadingState label={STRINGS.history.label} rows={2} />
        ) : overridesQuery.isError ? (
          <ErrorState
            title={STRINGS.history.failed}
            onRetry={() => void overridesQuery.refetch()}
          />
        ) : (
          <HistoryTable rows={overridesQuery.data.overrides} />
        )
      ) : null}
      {tab === "observations" ? <ObservationsSection edgeId={edgeId} active /> : null}

      {notice !== null ? (
        <div role="status" data-testid="decision-notice">
          {notice}
        </div>
      ) : null}

      {canCurate ? (
        <section
          className={styles.stack}
          aria-label={STRINGS.decide.heading}
          data-testid="decisions"
        >
          <Text weight="semibold">{STRINGS.decide.heading}</Text>
          {!bound ? <Text>{STRINGS.decide.noVersion}</Text> : null}
          <Field
            label={STRINGS.decide.confidence}
            validationState={confidenceValue === "invalid" ? "error" : "none"}
            validationMessage={
              confidenceValue === "invalid" ? STRINGS.decide.confidenceInvalid : undefined
            }
          >
            <Input value={confidenceText} onChange={(_e, d) => setConfidenceText(d.value)} />
          </Field>
          <div className={styles.actions}>
            {visible.map((d) => (
              <Button
                key={d}
                appearance={d === "accept" ? "primary" : "secondary"}
                disabled={!bound || confidenceValue === "invalid"}
                onClick={(e) => {
                  triggerRef.current = e.currentTarget;
                  setNotice(null);
                  setDialogError(null);
                  setPending(d);
                }}
              >
                {STRINGS.decide[d]}
              </Button>
            ))}
          </div>
        </section>
      ) : null}

      {pending !== null ? (
        <ChangeConfirmDialog
          open
          title={STRINGS.titles[pending]}
          target={edge.edge_id}
          version={`${edgeVersion ?? "unknown"} / ${edgeEtag ?? "unknown"}`}
          diff={decisionDiff(edge, pending, previewConfidence, "as entered")}
          showExpiry={needsExpiry(pending)}
          expiryRequired={needsExpiry(pending)}
          submitting={decide.isPending}
          error={dialogError}
          triggerRef={triggerRef}
          onSubmit={submit}
          onClose={close}
        />
      ) : null}
    </div>
  );
}

export function EdgePage(): ReactElement {
  const [params] = useSearchParams();
  const edgeId = params.get("edge_id")?.trim() ?? "";
  return (
    <PageTemplate title={STRINGS.pageTitle} description={STRINGS.pageDescription}>
      {edgeId === "" ? (
        <EmptyState title={STRINGS.noEdge} description={STRINGS.noEdgeHint} />
      ) : (
        <EdgeBody edgeId={edgeId} />
      )}
    </PageTemplate>
  );
}
