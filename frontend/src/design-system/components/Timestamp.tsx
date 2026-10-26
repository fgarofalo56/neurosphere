import { makeStyles } from "@fluentui/react-components";
import type { ReactElement } from "react";
import {
  UNKNOWN_TEXT,
  formatAbsoluteTime,
  formatRelativeTime,
  formatUtcDay,
  type TimeInput,
} from "../format";

const useStyles = makeStyles({
  hidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    overflow: "hidden",
    clipPath: "inset(50%)",
    whiteSpace: "nowrap",
  },
});

export interface TimestampProps {
  /** ISO string, epoch ms or Date; null/undefined/invalid renders "unknown". */
  readonly value: TimeInput;
  /** "day" values (billing days, report dates) are shown as a UTC calendar day, not relative. */
  readonly grain?: "instant" | "day";
  /** Reference time for relative text; pass a fixed value in tests. */
  readonly now?: TimeInput;
}

/**
 * `<time dateTime>` with relative text for instants. The absolute UTC value is in the `title`
 * and in the accessible name (visually hidden text), so relative wording never hides the date.
 */
export function Timestamp({ value, grain = "instant", now }: TimestampProps): ReactElement {
  const styles = useStyles();
  const date = value === null || value === undefined ? null : new Date(value);
  if (date === null || Number.isNaN(date.getTime())) {
    return <span data-slot="timestamp">{UNKNOWN_TEXT}</span>;
  }
  const iso = date.toISOString();
  if (grain === "day") {
    const day = formatUtcDay(date);
    return (
      <time dateTime={day} title={`${day} (UTC)`} data-slot="timestamp">
        {day}
        <span className={styles.hidden}> (UTC)</span>
      </time>
    );
  }
  const absolute = formatAbsoluteTime(date);
  return (
    <time dateTime={iso} title={absolute} data-slot="timestamp">
      {formatRelativeTime(date, now ?? new Date())}
      <span className={styles.hidden}> ({absolute})</span>
    </time>
  );
}
