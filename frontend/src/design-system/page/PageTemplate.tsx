import { makeStyles, tokens } from "@fluentui/react-components";
import { useId, type ReactElement, type ReactNode } from "react";
import { PageHeader } from "./PageHeader";
import { PageToolbar } from "./PageToolbar";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
  },
  content: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
    minWidth: 0,
  },
});

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
  readonly "data-testid"?: string;
  readonly children: ReactNode;
}

/**
 * Standard page layout: header (title, description, actions), optional toolbar, then content.
 * Render it as the root of every routed page; the app shell supplies `main`.
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
  children,
  "data-testid": testId,
}: PageTemplateProps): ReactElement {
  const styles = useStyles();
  const titleId = useId();
  return (
    <section
      className={styles.root}
      aria-labelledby={titleId}
      aria-busy={busy === true ? true : undefined}
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
      <div className={styles.content}>{children}</div>
    </section>
  );
}
