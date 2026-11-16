import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { NavLink } from "react-router";
import { ADMIN_AREAS } from "./areas";
import { ADMIN_HOME_PATH } from "./adminPaths";
import { ADMIN_STRINGS } from "./strings";

const useStyles = makeStyles({
  nav: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalXS,
  },
});

/** Links between the admin areas (and back to the console landing). Navigation only. */
export function AdminTabs(): ReactElement {
  const styles = useStyles();
  return (
    <nav aria-label={ADMIN_STRINGS.tabsLabel} className={styles.nav} data-testid="admin-tabs">
      <NavLink to={ADMIN_HOME_PATH} end>
        Console
      </NavLink>
      {ADMIN_AREAS.map((area) => (
        <NavLink key={area.id} to={area.to}>
          {area.label}
        </NavLink>
      ))}
    </nav>
  );
}
