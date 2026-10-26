import { makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import { useUiStyle } from "../../design-system";

const useStyles = makeStyles({
  card: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalM,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    width: "100%",
    maxWidth: "320px",
    boxSizing: "border-box",
  },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { ...shorthands.borderColor(tokens.colorNeutralStroke1) },
  small: { borderRadius: tokens.borderRadiusSmall },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  upper: { textTransform: "uppercase", letterSpacing: "0.06em", fontSize: tokens.fontSizeBase200 },
});

/** Class names for the map's side cards (legend, node panel), following the active style. */
export function useCardClasses(): { readonly card: string; readonly title: string } {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  return {
    card: mergeClasses(
      styles.card,
      treatment.panelSurface === "lifted" && styles.lifted,
      treatment.surface === "raised" && styles.raised,
      treatment.border === "strong" && styles.strong,
      treatment.radius === "small" && styles.small,
    ),
    title: mergeClasses(styles.title, treatment.uppercaseLabels && styles.upper),
  };
}
