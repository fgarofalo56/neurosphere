import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { KpiCard } from "../../../design-system";
import { useMatchCompleteness, useMatchMetrics } from "./hooks";
import { MATCH_STRINGS } from "./strings";

const useStyles = makeStyles({
  strip: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    margin: 0,
    padding: 0,
  },
  note: { color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
});

export function percentText(rate: number | null): string {
  return rate === null ? MATCH_STRINGS.metrics.noFeedback : `${String(Math.round(rate * 100))}%`;
}

/** Matches, accepts, rejects and acceptance rate, plus the optional completeness tile. */
export function MatchMetricsStrip({ domainId }: { readonly domainId: string }): ReactElement {
  const styles = useStyles();
  const M = MATCH_STRINGS.metrics;
  const metrics = useMatchMetrics({ domainId });
  const completeness = useMatchCompleteness({});

  const completenessValue =
    completeness.data?.state === "present" && typeof completeness.data.data.ratio === "number"
      ? percentText(completeness.data.data.ratio)
      : MATCH_STRINGS.completeness.notAvailable;

  return (
    <section aria-label={M.section} data-testid="match-metrics">
      <h2>{M.title}</h2>
      <div className={styles.strip}>
        {metrics.isError ? (
          <p data-testid="match-metrics-unavailable">{M.unavailable}</p>
        ) : metrics.isPending ? (
          <p aria-busy="true">{MATCH_STRINGS.loading}</p>
        ) : (
          <>
            <KpiCard label={M.matches} value={String(metrics.data.matches)} />
            <KpiCard label={M.accepts} value={String(metrics.data.accepts)} />
            <KpiCard label={M.rejects} value={String(metrics.data.rejects)} />
            <KpiCard
              label={M.acceptanceRate}
              value={percentText(metrics.data.acceptance_rate)}
              testId="match-acceptance-rate"
            />
          </>
        )}
        <KpiCard
          label={MATCH_STRINGS.completeness.title}
          value={completenessValue}
          testId="match-completeness"
        />
      </div>
      <p className={styles.note} data-testid="match-outcome-note">
        {M.outcomeNote}
      </p>
    </section>
  );
}
