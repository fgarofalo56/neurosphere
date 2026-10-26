import { makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
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
  const { density } = useUiStyle();
  const compact = density === "compact";
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
          data-slot="page-kpis"
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
