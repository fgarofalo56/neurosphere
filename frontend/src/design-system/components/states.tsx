import {
  Button,
  Skeleton,
  SkeletonItem,
  Text,
  makeStyles,
  mergeClasses,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";

const useStyles = makeStyles({
  box: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    rowGap: tokens.spacingVerticalS,
    padding: tokens.spacingHorizontalL,
    border: `${tokens.strokeWidthThin} dashed ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1,
  },
  error: {
    ...shorthands.borderStyle("solid"),
    ...shorthands.borderColor(tokens.colorStatusDangerBorder1),
    backgroundColor: tokens.colorStatusDangerBackground1,
  },
  warning: {
    ...shorthands.borderStyle("solid"),
    ...shorthands.borderColor(tokens.colorStatusWarningBorder1),
    backgroundColor: tokens.colorStatusWarningBackground1,
  },
  title: { fontWeight: tokens.fontWeightSemibold, overflowWrap: "anywhere" },
  skeleton: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalS },
});

export interface EmptyStateProps {
  readonly title: string;
  readonly description?: ReactNode;
  /** Optional call to action (a Fluent Button). */
  readonly action?: ReactNode;
  /** Rendered as `data-testid` on the root element. */
  readonly testId?: string;
}

/** "Nothing here" panel. Uses text, not a heading, so it never changes the page outline. */
export function EmptyState({ title, description, action, testId }: EmptyStateProps): ReactElement {
  const styles = useStyles();
  return (
    <div className={styles.box} data-slot="empty-state" data-testid={testId}>
      <Text className={styles.title}>{title}</Text>
      {description === undefined ? null : <Text>{description}</Text>}
      {action}
    </div>
  );
}

export interface LoadingStateProps {
  /** Accessible name of the loading region. Defaults to "Loading". */
  readonly label?: string;
  /** Number of skeleton rows. Defaults to 3. */
  readonly rows?: number;
  /** Rendered as `data-testid` on the root element. */
  readonly testId?: string;
}

/** Skeleton placeholder for content that is loading. */
export function LoadingState({
  label = "Loading",
  rows = 3,
  testId,
}: LoadingStateProps): ReactElement {
  const styles = useStyles();
  return (
    <Skeleton
      aria-label={label}
      className={styles.skeleton}
      data-slot="loading-state"
      data-testid={testId}
    >
      {Array.from({ length: Math.max(1, rows) }, (_, i) => (
        <SkeletonItem key={i} size={16} />
      ))}
    </Skeleton>
  );
}

export interface ErrorStateProps {
  readonly title: string;
  readonly message?: ReactNode;
  /** When set, a "Try again" button calls it. */
  readonly onRetry?: () => void;
  /** Optional control row (e.g. a Fluent Button with its own label), shown after the message. */
  readonly action?: ReactNode;
  /** "warning" for a refused request (403) instead of the default failure look. */
  readonly tone?: "danger" | "warning";
  /** Rendered as `data-testid` on the root element. */
  readonly testId?: string;
}

/** Error panel announced to assistive tech (`role="alert"`). */
export function ErrorState({
  title,
  message,
  onRetry,
  action,
  tone = "danger",
  testId,
}: ErrorStateProps): ReactElement {
  const styles = useStyles();
  return (
    <div
      className={mergeClasses(styles.box, tone === "warning" ? styles.warning : styles.error)}
      role="alert"
      data-slot="error-state"
      data-testid={testId}
    >
      <Text className={styles.title}>{title}</Text>
      {message === undefined ? null : <Text>{message}</Text>}
      {onRetry === undefined ? null : <Button onClick={onRetry}>Try again</Button>}
      {action}
    </div>
  );
}
