import { Button, Text, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { useNavigate } from "react-router";
import { ChartFrame } from "../charts";
import { SaveReportDialog, type StructuredQuery } from "../reports";
import { defaultQuerySpec, singleDomain } from "./saveQuery";
import { STRINGS } from "./strings";
import type {
  ActionSuggestionEvent,
  AssistantTurn,
  CitationEvent,
  ContextEcho,
  FilterValue,
} from "./types";

const useStyles = makeStyles({
  chip: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
    padding: tokens.spacingVerticalXS,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground2,
  },
  list: { margin: 0, paddingLeft: tokens.spacingHorizontalL },
  block: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalXS },
  user: { fontWeight: tokens.fontWeightSemibold },
  card: {
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    padding: tokens.spacingVerticalS,
  },
  notice: {
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    padding: tokens.spacingVerticalS,
    backgroundColor: tokens.colorNeutralBackground3,
  },
});

function filterText(value: FilterValue): string {
  return typeof value === "string" ? value : value.join("|");
}

/** The server's echo of the context it used for the question; never the client's request. */
export function ContextChip({ echo }: { readonly echo: ContextEcho | null }): ReactElement {
  const styles = useStyles();
  const C = STRINGS.context;
  if (echo === null) {
    return (
      <div className={styles.chip} data-testid="context-chip" role="group" aria-label={C.label}>
        <Text size={200}>{C.none}</Text>
      </div>
    );
  }
  const filters = Object.entries(echo.filters).map(([k, v]) => `${k}=${filterText(v)}`);
  const dropped = echo.dropped_selection_count;
  return (
    <div className={styles.chip} data-testid="context-chip" role="group" aria-label={C.label}>
      <Text size={200}>
        {C.page}: {echo.page ?? "none"}
      </Text>
      <Text size={200}>
        {C.route}: {echo.route ?? "none"}
      </Text>
      <Text size={200}>
        {C.filters}: {filters.length === 0 ? C.noFilters : filters.join(", ")}
      </Text>
      <Text size={200}>
        {C.timeRange}:{" "}
        {echo.time_range === null ? "none" : `${echo.time_range.from} to ${echo.time_range.to}`}
      </Text>
      <Text size={200}>
        {C.selection}: {echo.selection.length === 0 ? C.noSelection : echo.selection.join(", ")}
      </Text>
      <Text size={200}>
        {C.domains}: {echo.applied_domains.length === 0 ? "none" : echo.applied_domains.join(", ")}
      </Text>
      {dropped > 0 ? (
        <Text size={200} role="status">
          {dropped === 1 ? C.droppedOne : C.droppedMany(dropped)}
        </Text>
      ) : null}
    </div>
  );
}

/** Answer handles like `[cite:r1]` read as `[r1]`; the matching source is listed below. */
export function displayText(text: string): string {
  return text.replace(/\[cite:([A-Za-z0-9_.:-]+)\]/g, "[$1]");
}

export function CitationList({
  citations,
}: {
  readonly citations: readonly CitationEvent[];
}): ReactElement | null {
  const styles = useStyles();
  if (citations.length === 0) return null;
  const C = STRINGS.citations;
  return (
    <div className={styles.block}>
      <Text weight="semibold" size={200}>
        {C.label}
      </Text>
      <ol className={styles.list} aria-label={C.label} data-testid="citations">
        {citations.map((c) => (
          <li key={c.record_id} data-freshness={c.freshness}>
            <Text size={200}>
              [{c.record_id}] {c.kind} from {c.source}. <strong>{C.freshness[c.freshness]}</strong>,{" "}
              {c.as_of === null ? C.asOfUnknown : `${C.asOf} ${c.as_of}`}
            </Text>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** href of the existing PRP-17 action detail route, which hosts the confirmation dialog. */
export function actionDetailHref(domainId: string, intentId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, intent_id: intentId });
  return `/actions/detail?${p.toString()}`;
}

function targetLabel(target: Readonly<Record<string, unknown>>): string {
  const id = target["canonical_id"];
  return typeof id === "string" ? id : "";
}

/**
 * A drafted action from the assistant. There is deliberately NO confirm or execute control
 * here: the button opens the PRP-17 action page for the drafted intent, where the exact target,
 * version and diff are shown and the confirmation dialog rechecks permission and approvals.
 */
export function ActionSuggestionCard({
  suggestion,
  onNavigate,
}: {
  readonly suggestion: ActionSuggestionEvent;
  readonly onNavigate: () => void;
}): ReactElement {
  const styles = useStyles();
  const navigate = useNavigate();
  const S = STRINGS.suggestion;
  const target = targetLabel(suggestion.target);
  return (
    <div className={styles.card} data-testid="action-suggestion" role="group" aria-label={S.label}>
      <Text weight="semibold">{S.label}</Text>
      <div>
        <Text size={200}>
          {suggestion.action_type}
          {target === "" ? "" : ` on ${target}`}
        </Text>
      </div>
      <Text size={200}>{S.help}</Text>
      <div>
        <Button
          appearance="primary"
          onClick={() => {
            onNavigate();
            void navigate(actionDetailHref(suggestion.domain_id, suggestion.intent_id));
          }}
        >
          {S.review}
        </Button>
      </div>
    </div>
  );
}

export function AssistantTurnView({
  turn,
  echo,
  onNavigate,
}: {
  readonly turn: AssistantTurn;
  readonly echo: ContextEcho | null;
  readonly onNavigate: () => void;
}): ReactElement {
  const styles = useStyles();
  const timing =
    !import.meta.env.PROD && turn.firstTokenMs !== null
      ? { "data-first-token-ms": turn.firstTokenMs.toFixed(1) }
      : {};
  const emptyStreaming = turn.status === "streaming" && turn.text === "";
  return (
    <div className={styles.block}>
      <Text className={styles.user}>
        {STRINGS.you}: {turn.userText}
      </Text>
      <div
        className={styles.block}
        data-testid="assistant-turn"
        data-status={turn.status}
        {...timing}
      >
        <Text weight="semibold" size={200}>
          {STRINGS.assistant}
        </Text>
        {turn.tools.length > 0 ? (
          <ul className={styles.list} aria-label={STRINGS.tools.label} data-testid="tools">
            {turn.tools.map((t) => (
              <li key={t.name}>
                <Text size={200}>
                  {t.name}: {STRINGS.tools[t.status]}
                </Text>
              </li>
            ))}
          </ul>
        ) : null}
        {emptyStreaming ? <Text size={200}>{STRINGS.working}</Text> : null}
        {turn.text !== "" ? <p data-testid="answer-text">{displayText(turn.text)}</p> : null}
        {turn.status === "abstain" || turn.status === "denied" ? (
          <div className={styles.notice} data-testid={turn.status}>
            <Text weight="semibold">
              {turn.status === "abstain" ? STRINGS.abstain.title : STRINGS.denied.title}
            </Text>
            <div>
              <Text>
                {turn.status === "abstain" ? STRINGS.abstain.prefix : STRINGS.denied.prefix}{" "}
                {turn.reason?.reason}
              </Text>
            </div>
            <Text size={200}>Reason code: {turn.reason?.reason_code}</Text>
          </div>
        ) : null}
        {turn.status === "error" ? (
          <div role="alert" className={styles.notice} data-testid="turn-error">
            <Text weight="semibold">{STRINGS.errorTitle}</Text>
            <div>
              <Text>{turn.failure?.detail}</Text>
            </div>
          </div>
        ) : null}
        <CitationList citations={turn.citations} />
        {turn.charts.map((plan, i) => (
          <div key={`chart-${i}`} className={styles.block} data-testid="assistant-chart">
            <ChartFrame plan={plan} title={STRINGS.chart.title} height={240} />
            <SaveReportDialog
              chartPlan={plan}
              querySpec={defaultQuerySpec(echo) as unknown as StructuredQuery}
              domainId={singleDomain(echo)}
              defaultTitle={plan.spec.title ?? ""}
            />
          </div>
        ))}
        {turn.suggestions.map((s) => (
          <ActionSuggestionCard key={s.intent_id} suggestion={s} onNavigate={onNavigate} />
        ))}
      </div>
    </div>
  );
}
