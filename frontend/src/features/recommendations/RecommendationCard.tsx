import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { Link } from "react-router";
import { Timestamp, useUiStyle } from "../../design-system";
import { AdvisoryBadge, EvidenceStatus, Facts } from "./components";
import { KIND_LABELS } from "./strings";
import type { Recommendation } from "./types";

const useStyles = makeStyles({
  card: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalL,
    listStyleType: "none",
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { borderTopColor: tokens.colorNeutralStroke1 },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  head: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXS,
  },
  title: { fontSize: tokens.fontSizeBase400, fontWeight: tokens.fontWeightSemibold },
  subjects: { color: tokens.colorNeutralForeground2, overflowWrap: "anywhere" },
  foot: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalM,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase200,
  },
});

/** One recommendation as a card: kind link, advisory pill, subjects, impact, confidence, owner. */
export function RecommendationCard({
  rec,
  href,
}: {
  readonly rec: Recommendation;
  readonly href: string;
}): ReactElement {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  return (
    <li
      data-testid="recommendation-row"
      data-slot="recommendation-card"
      className={mergeClasses(
        styles.card,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.surface === "raised" && styles.raised,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
    >
      <div className={styles.head}>
        <Link to={href} className={styles.title}>
          {KIND_LABELS[rec.kind]}
        </Link>
        <AdvisoryBadge advisory={rec.advisory} />
      </div>
      <div className={styles.subjects}>{rec.subject_ids.join(", ")}</div>
      <Facts rec={rec} />
      <div className={styles.foot}>
        <span>
          Evidence: <EvidenceStatus rec={rec} />
        </span>
        <span>
          Created: <Timestamp value={rec.created_at} />
        </span>
      </div>
    </li>
  );
}
