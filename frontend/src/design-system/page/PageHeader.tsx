import { Text, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement, ReactNode } from "react";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-start",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalS,
  },
  text: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalXS,
    minWidth: 0,
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeHero700,
    lineHeight: tokens.lineHeightHero700,
    fontWeight: tokens.fontWeightSemibold,
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
  },
});

export interface PageHeaderProps {
  /** Page title, rendered as the page's single `h1`. */
  readonly title: string;
  /** One line under the title saying what the page shows. */
  readonly description?: ReactNode;
  /** Page-level actions (buttons, menus), aligned to the end. */
  readonly actions?: ReactNode;
  /** `id` placed on the `h1`, so a wrapping region can use `aria-labelledby`. */
  readonly titleId?: string;
}

/** Title, description and actions row of a page. Use through `PageTemplate` unless you need it alone. */
export function PageHeader({
  title,
  description,
  actions,
  titleId,
}: PageHeaderProps): ReactElement {
  const styles = useStyles();
  return (
    <div className={styles.root} data-slot="page-header">
      <div className={styles.text}>
        <h1 className={styles.title} id={titleId}>
          {title}
        </h1>
        {description === undefined ? null : <Text>{description}</Text>}
      </div>
      {actions === undefined ? null : <div className={styles.actions}>{actions}</div>}
    </div>
  );
}
