import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import {
  Children,
  Fragment,
  isValidElement,
  useId,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from "react";
import { useUiStyle } from "../styles";
import { PageHeader } from "./PageHeader";
import { PageToolbar } from "./PageToolbar";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
  },
  rootCompact: { rowGap: tokens.spacingVerticalS },
  content: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    minWidth: 0,
  },
  contentCompact: { rowGap: tokens.spacingVerticalS },
  kpis: {
    display: "grid",
    // Fallback when the card count is unknown; normally overridden inline by kpiGridColumns().
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
  kpisCompact: { columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
  split: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
});

/** Counts KPI children, looking through fragments and arrays; null/false children do not count. */
export function countKpis(node: ReactNode): number {
  let n = 0;
  for (const child of Children.toArray(node)) {
    if (isValidElement<{ children?: ReactNode }>(child) && child.type === Fragment) {
      n += countKpis(child.props.children);
    } else {
      n += 1;
    }
  }
  return n;
}

/**
 * Columns for N KPI cards so rows fill evenly (never one orphan card on the last row): all N across
 * when they fit under `maxAcross`, otherwise the largest divisor of N not above it (6 cards become
 * 3x2), otherwise the fewest balanced rows.
 */
export function kpiColumns(count: number, maxAcross: number): number {
  if (count <= 1) return 1;
  const max = Math.max(1, Math.floor(maxAcross));
  if (count <= max) return count;
  for (let c = max; c >= 2; c -= 1) {
    if (count % c === 0) return c;
  }
  return Math.ceil(count / Math.ceil(count / max));
}

/** Grid track list: `cols` equal columns on wide containers, fewer (never uneven) on narrow ones. */
function kpiGridStyle(cols: number, gap: string): CSSProperties {
  const min = `max(150px, calc((100% - ${cols - 1} * ${gap}) / ${cols} - 1px))`;
  return { gridTemplateColumns: `repeat(auto-fit, minmax(${min}, 1fr))` };
}

/** Content arrangement: "stack" (default, v1 behaviour), "grid" (auto-fit cards) or "split". */
export type PageLayout = "stack" | "grid" | "split";

export interface PageTemplateProps {
  /** Page title (the page's one `h1`); also the accessible name of the page region. */
  readonly title: string;
  readonly description?: ReactNode;
  /** Page-level actions shown beside the title. */
  readonly actions?: ReactNode;
  /** Filter controls shown in a `PageToolbar` under the header; omit for no toolbar. */
  readonly toolbar?: ReactNode;
  /** Accessible name of the toolbar group. Defaults to "Filters". */
  readonly toolbarLabel?: string;
  /** Set while the page content is loading. */
  readonly busy?: boolean;
  /** v2: KPI cards shown in a responsive row between the toolbar and the content. */
  readonly kpis?: ReactNode;
  /** v2: how `children` are arranged. Defaults to "stack" (the v1 behaviour). */
  readonly layout?: PageLayout;
  readonly "data-testid"?: string;
  readonly children: ReactNode;
}

/**
 * Standard page layout: header (title, description, actions), optional toolbar, optional KPI
 * row, then content. Spacing follows the active UI style's density. Render it as the root of
 * every routed page; the app shell supplies `main`.
 *
 * ```tsx
 * const { domainId } = useSelectedDomain();
 * <PageTemplate title="Review queue" toolbar={<Field label="State">...</Field>}>
 *   ...
 * </PageTemplate>
 * ```
 */
export function PageTemplate({
  title,
  description,
  actions,
  toolbar,
  toolbarLabel,
  busy,
  kpis,
  layout = "stack",
  children,
  "data-testid": testId,
}: PageTemplateProps): ReactElement {
  const styles = useStyles();
  const titleId = useId();
  const { density, treatment } = useUiStyle();
  const compact = density === "compact";
  const kpiCols = kpis === undefined ? 1 : kpiColumns(countKpis(kpis), treatment.kpiMaxAcross);
  return (
    <section
      className={mergeClasses(styles.root, compact && styles.rootCompact)}
      aria-labelledby={titleId}
      aria-busy={busy === true ? true : undefined}
      data-density={density}
      data-testid={testId}
    >
      <PageHeader
        title={title}
        titleId={titleId}
        {...(description === undefined ? {} : { description })}
        {...(actions === undefined ? {} : { actions })}
      />
      {toolbar === undefined ? null : (
        <PageToolbar {...(toolbarLabel === undefined ? {} : { label: toolbarLabel })}>
          {toolbar}
        </PageToolbar>
      )}
      {kpis === undefined ? null : (
        <div
          className={mergeClasses(styles.kpis, compact && styles.kpisCompact)}
          style={kpiGridStyle(
            kpiCols,
            compact ? tokens.spacingHorizontalS : tokens.spacingHorizontalM,
          )}
          data-slot="page-kpis"
          data-kpi-columns={kpiCols}
        >
          {kpis}
        </div>
      )}
      <div
        className={mergeClasses(
          styles.content,
          compact && styles.contentCompact,
          layout === "grid" && styles.grid,
          layout === "split" && styles.split,
        )}
        data-layout={layout}
      >
        {children}
      </div>
    </section>
  );
}
