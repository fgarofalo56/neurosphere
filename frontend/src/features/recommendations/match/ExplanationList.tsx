import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { MATCH_STRINGS, SIGNAL_LABELS } from "./strings";
import type { AgentMatchSignal } from "./types";
import { formatRatio } from "./types";

const useStyles = makeStyles({
  table: { borderCollapse: "collapse", width: "100%", fontSize: tokens.fontSizeBase200 },
  cell: {
    textAlign: "left",
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS}`,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  caption: { textAlign: "left", fontWeight: tokens.fontWeightSemibold },
});

/** Observed state as text. A null value is "no telemetry yet", never a 0. */
export function observedText(signal: AgentMatchSignal): string {
  return signal.value == null
    ? MATCH_STRINGS.noTelemetry
    : `${MATCH_STRINGS.explanation.observedValue} (${formatRatio(signal.value)})`;
}

/** One row per ranking signal; unobserved signals are stated in words, not by color. */
export function ExplanationList({
  signals,
}: {
  readonly signals: readonly AgentMatchSignal[];
}): ReactElement {
  const styles = useStyles();
  const L = MATCH_STRINGS.explanation;
  return (
    <table className={styles.table} data-testid="match-explanation">
      <caption className={styles.caption}>{L.caption}</caption>
      <thead>
        <tr>
          <th scope="col" className={styles.cell}>
            {L.signal}
          </th>
          <th scope="col" className={styles.cell}>
            {L.observed}
          </th>
          <th scope="col" className={styles.cell}>
            {L.weight}
          </th>
          <th scope="col" className={styles.cell}>
            {L.contribution}
          </th>
        </tr>
      </thead>
      <tbody>
        {signals.map((s) => (
          <tr key={s.signal} data-testid="match-signal" data-observed={String(s.value != null)}>
            <th scope="row" className={styles.cell}>
              {SIGNAL_LABELS[s.signal]}
            </th>
            <td className={styles.cell}>{observedText(s)}</td>
            <td className={styles.cell}>{formatRatio(s.weight)}</td>
            <td className={styles.cell}>
              {s.value == null ? L.notCounted : formatRatio(s.contribution)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
