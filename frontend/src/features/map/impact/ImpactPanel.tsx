import { Button, Select, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { HEALTH_LABEL, TRUNCATION_REASON_LABEL, kindLabel } from "../strings";
import { useCardClasses } from "../card";
import type { ImpactRow, ImpactState } from "./impactState";
import { IMPACT_STRINGS as S } from "./strings";
import { MAX_IMPACT_DEPTH, MIN_IMPACT_DEPTH } from "./useMapImpact";

const useStyles = makeStyles({
  heading: { margin: 0, fontSize: tokens.fontSizeBase300, fontWeight: tokens.fontWeightSemibold },
  muted: { margin: 0, color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200 },
  list: {
    margin: 0,
    paddingInlineStart: tokens.spacingHorizontalL,
    display: "grid",
    rowGap: "4px",
  },
  item: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.spacingHorizontalS },
  controls: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: tokens.spacingHorizontalS,
  },
});

export interface ImpactPanelProps {
  readonly rootLabel: string;
  readonly depth: number;
  readonly onDepth: (depth: number) => void;
  /** Null until the first answer arrives. */
  readonly state: ImpactState | null;
  readonly loading: boolean;
  readonly failed: boolean;
  readonly onClear: () => void;
  /** Bring an off-screen dependent onto the map. */
  readonly onShowOnMap: (row: ImpactRow) => void;
}

function rowText(row: ImpactRow): string {
  const health = HEALTH_LABEL[row.health];
  return S.row(
    row.label,
    kindLabel(row.kind),
    row.healthInferred ? `${health} (${S.inferred})` : health,
  );
}

/**
 * The text form of the incident view: every dependent by depth with its health as words. The
 * highlight on the canvas is a ring plus this list, never colour alone.
 */
export function ImpactPanel({
  rootLabel,
  depth,
  onDepth,
  state,
  loading,
  failed,
  onClear,
  onShowOnMap,
}: ImpactPanelProps): ReactElement {
  const styles = useStyles();
  const card = useCardClasses();
  const reason = state?.truncationReason ?? null;
  return (
    <section className={card.card} aria-label={S.panelLabel} data-testid="impact-panel">
      <h2 className={card.title}>{S.heading}</h2>
      <p className={styles.muted}>{S.intro(rootLabel)}</p>
      <div className={styles.controls}>
        <label htmlFor="impact-depth">{S.depthLabel}</label>
        <Select
          id="impact-depth"
          data-testid="impact-depth"
          value={String(depth)}
          onChange={(_, data) => onDepth(Number(data.value))}
        >
          {Array.from({ length: MAX_IMPACT_DEPTH - MIN_IMPACT_DEPTH + 1 }, (_, i) => (
            <option key={i} value={String(MIN_IMPACT_DEPTH + i)}>
              {MIN_IMPACT_DEPTH + i}
            </option>
          ))}
        </Select>
        <Button appearance="secondary" size="small" onClick={onClear} data-testid="impact-clear">
          {S.clearImpact}
        </Button>
      </div>
      <div role="status" aria-live="polite" data-testid="impact-status">
        {state !== null ? S.affected(state.total, rootLabel) : loading ? S.loading : ""}
      </div>
      {failed ? <p role="alert">{S.failed}</p> : null}
      {state !== null && state.truncated ? (
        <p className={styles.muted}>
          {S.truncated(reason !== null ? TRUNCATION_REASON_LABEL[reason] : S.truncatedFallback)}
        </p>
      ) : null}
      <div data-testid="impact-list">
        {state !== null && state.total === 0 ? <p>{S.none(depth)}</p> : null}
        {state?.levels
          .filter((level) => level.rows.length > 0)
          .map((level) => (
            <div key={level.depth} data-testid={`impact-depth-${level.depth}`}>
              <h3 className={styles.heading}>{S.levelHeading(level.depth)}</h3>
              <ul className={styles.list}>
                {level.rows.map((row) => (
                  <li key={row.id} className={styles.item} data-testid="impact-row">
                    <span>{rowText(row)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
      {state !== null && state.offscreen.length > 0 ? (
        <div data-testid="impact-offscreen">
          <h3 className={styles.heading}>{S.offscreenHeading}</h3>
          <p className={styles.muted}>{S.offscreenNote}</p>
          <ul className={styles.list}>
            {state.offscreen.map((row) => (
              <li key={row.id} className={styles.item} data-testid="impact-offscreen-row">
                <span>{rowText(row)}</span>
                <Button
                  size="small"
                  appearance="secondary"
                  aria-label={S.showOnMapNamed(row.label)}
                  onClick={() => onShowOnMap(row)}
                >
                  {S.showOnMap}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className={styles.muted}>{S.shortcut}</p>
    </section>
  );
}
