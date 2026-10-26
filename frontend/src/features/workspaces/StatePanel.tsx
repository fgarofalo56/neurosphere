import { Text, makeStyles, mergeClasses, shorthands, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";

const useStyles = makeStyles({
  box: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingHorizontalL,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
    ...shorthands.borderStyle("solid"),
    ...shorthands.borderWidth(tokens.strokeWidthThin),
    borderInlineStartWidth: tokens.strokeWidthThickest,
  },
  warning: {
    ...shorthands.borderColor(tokens.colorStatusWarningBorder1),
    backgroundColor: tokens.colorStatusWarningBackground1,
  },
  danger: {
    ...shorthands.borderColor(tokens.colorStatusDangerBorder1),
    backgroundColor: tokens.colorStatusDangerBackground1,
  },
  title: { fontWeight: tokens.fontWeightSemibold, overflowWrap: "anywhere" },
  body: { overflowWrap: "anywhere" },
});

export interface StatePanelProps {
  /** "warning" for a refused request (403), "danger" for a failed one. */
  readonly tone: "warning" | "danger";
  readonly title: string;
  /** Explanation; plain text or a short fragment. */
  readonly children?: ReactNode;
  /** Optional control row, e.g. a Fluent "Retry" Button. */
  readonly action?: ReactNode;
  readonly "data-testid"?: string;
}

/**
 * Alert panel in the shape of the design-system `ErrorState` (same box, spacing and radius), with
 * a `data-testid` hook and a warning tone for access-denied. It carries `role="alert"` itself, so
 * the element a test finds by id is the element assistive tech announces.
 */
export function StatePanel({
  tone,
  title,
  children,
  action,
  "data-testid": testId,
}: StatePanelProps): ReactElement {
  const styles = useStyles();
  return (
    <div
      className={mergeClasses(styles.box, styles[tone])}
      role="alert"
      data-slot="error-state"
      data-tone={tone}
      data-testid={testId}
    >
      <Text className={styles.title}>{title}</Text>
      {children === undefined ? null : <Text className={styles.body}>{children}</Text>}
      {action}
    </div>
  );
}
