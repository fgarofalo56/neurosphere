import {
  Hamburger,
  NavDrawer,
  NavItem as FluentNavItem,
  NavSectionHeader,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useEffect, useId, useMemo, useRef, useState, type ReactElement } from "react";
import { Outlet, useHref, useLinkClickHandler, useLocation } from "react-router";
import { useRoles } from "../auth";
import { LogoSlot } from "../design-system";
import { CopilotDock } from "../features/copilot/CopilotDock";
import { DomainSwitcher } from "./DomainSwitcher";
import { ErrorBoundary } from "./ErrorBoundary";
import { UserMenu } from "./UserMenu";
import { useDomainData, useSelectedDomain } from "./domain";
import {
  groupNavItems,
  isNavItemVisible,
  selectedNavTo,
  withDomain,
  type NavItem,
} from "./navigation";

export const PRODUCT_NAME = "NeuroSphere";
export const MAIN_ID = "main-content";

const NAV_WIDTH = "220px";
const COMPACT_QUERY = "(max-width: 720px)";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    minHeight: "100vh",
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
  },
  skip: {
    position: "absolute",
    insetInlineStart: tokens.spacingHorizontalM,
    insetBlockStart: "-100px",
    zIndex: 1000,
    paddingBlock: tokens.spacingVerticalS,
    paddingInline: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    border: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}`,
    borderRadius: tokens.borderRadiusMedium,
    ":focus": { insetBlockStart: tokens.spacingVerticalM },
  },
  header: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    paddingBlock: tokens.spacingVerticalS,
    paddingInline: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  product: {
    fontSize: tokens.fontSizeBase500,
    fontWeight: tokens.fontWeightSemibold,
  },
  spacer: { flexGrow: 1 },
  body: { display: "flex", flexGrow: 1, minHeight: 0 },
  nav: { width: NAV_WIDTH, flexShrink: 0 },
  // Plain container, not NavDrawerBody: its tabster Mover injects aria-hidden focus sentinels on
  // every page, which axe reports as aria-hidden-focus.
  navBody: {
    display: "flex",
    flexDirection: "column",
    paddingBlock: tokens.spacingVerticalS,
    overflowY: "auto",
  },
  group: { display: "flex", flexDirection: "column" },
  main: {
    flexGrow: 1,
    minWidth: 0,
    paddingBlock: tokens.spacingVerticalL,
    paddingInline: tokens.spacingHorizontalL,
    ":focus": { outlineStyle: "none" },
  },
});

/** True on narrow viewports, where the drawer becomes an overlay opened by the hamburger. */
function useCompact(): boolean {
  const [compact, setCompact] = useState(() => matches());
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia(COMPACT_QUERY);
    const onChange = (): void => setCompact(query.matches);
    query.addEventListener("change", onChange);
    onChange();
    return () => query.removeEventListener("change", onChange);
  }, []);
  return compact;
}

function matches(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(COMPACT_QUERY).matches;
}

/** A real anchor (open in new tab, copy link) that navigates client-side on a plain click. */
function ShellNavLink({
  item,
  domainId,
  onNavigate,
}: {
  readonly item: NavItem;
  readonly domainId: string;
  readonly onNavigate: () => void;
}): ReactElement {
  const to = withDomain(item.to, domainId);
  const href = useHref(to);
  const handleClick = useLinkClickHandler(to);
  return (
    <FluentNavItem
      as="a"
      href={href}
      value={item.to}
      onClick={(event) => {
        handleClick(event);
        onNavigate();
      }}
    >
      {item.label}
    </FluentNavItem>
  );
}

function ShellNav({
  sections,
  allItems,
  compact,
  navOpen,
  setNavOpen,
}: {
  readonly sections: ReturnType<typeof groupNavItems>;
  readonly allItems: readonly NavItem[];
  readonly compact: boolean;
  readonly navOpen: boolean;
  readonly setNavOpen: (open: boolean) => void;
}): ReactElement {
  const styles = useStyles();
  const idBase = useId();
  const { pathname } = useLocation();
  const { domainId } = useSelectedDomain();
  const selected = selectedNavTo(allItems, pathname);
  return (
    <NavDrawer
      aria-label="Primary"
      data-slot="navigation"
      className={compact ? undefined : styles.nav}
      type={compact ? "overlay" : "inline"}
      open={compact ? navOpen : true}
      onOpenChange={(_event, data) => setNavOpen(data.open)}
      {...(selected === undefined ? {} : { selectedValue: selected })}
    >
      <div className={styles.navBody}>
        {sections.map((section, index) => {
          const links = section.items.map((item) => (
            <ShellNavLink
              key={item.to}
              item={item}
              domainId={domainId}
              onNavigate={() => setNavOpen(false)}
            />
          ));
          if (section.group === undefined) return <div key="ungrouped">{links}</div>;
          const headingId = `${idBase}-${index}`;
          return (
            <div
              key={section.group}
              role="group"
              aria-labelledby={headingId}
              className={styles.group}
            >
              {/* role=presentation: a visible label for the group without adding a heading to the page outline. */}
              <NavSectionHeader id={headingId} role="presentation">
                {section.group}
              </NavSectionHeader>
              {links}
            </div>
          );
        })}
      </div>
    </NavDrawer>
  );
}

export interface ShellProps {
  readonly staticItems: readonly NavItem[];
  readonly useNavItems: (() => readonly NavItem[]) | undefined;
}

/**
 * The app shell every route renders inside: skip link, header (product, logo slot, domain
 * switcher, user menu), grouped permission-aware navigation, `main`, and the one CopilotDock.
 */
export function Shell({ staticItems, useNavItems }: ShellProps): ReactElement {
  const styles = useStyles();
  const items = useNavItems === undefined ? staticItems : useNavItems();
  const { roles } = useRoles();
  const data = useDomainData();
  const permissions = data?.permissions;
  const compact = useCompact();
  const [navOpen, setNavOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);

  // The browser's default 8px body margin would inset the shell; there is no global stylesheet.
  useEffect(() => {
    const previous = document.body.style.margin;
    document.body.style.margin = "0";
    return () => {
      document.body.style.margin = previous;
    };
  }, []);

  const visible = useMemo(() => {
    const held = permissions ?? new Set<string>();
    return items.filter((item) => isNavItemVisible(item, { roles, permissions: held }));
  }, [items, roles, permissions]);
  const sections = useMemo(() => groupNavItems(visible), [visible]);

  return (
    <div className={styles.root}>
      <a
        href={`#${MAIN_ID}`}
        className={styles.skip}
        onClick={(event) => {
          event.preventDefault();
          mainRef.current?.focus();
        }}
      >
        Skip to main content
      </a>
      <header className={styles.header}>
        {compact ? (
          <Hamburger aria-label="Open navigation" onClick={() => setNavOpen(true)} />
        ) : null}
        <LogoSlot />
        <span className={styles.product}>{PRODUCT_NAME}</span>
        <span className={styles.spacer} />
        <DomainSwitcher />
        <UserMenu />
      </header>
      <div className={styles.body}>
        <ShellNav
          sections={sections}
          allItems={visible}
          compact={compact}
          navOpen={navOpen}
          setNavOpen={setNavOpen}
        />
        <main id={MAIN_ID} ref={mainRef} tabIndex={-1} className={styles.main}>
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      {/* Copilot slot: mounted once in the authenticated shell (PRP-19). */}
      <ErrorBoundary>
        <CopilotDock />
      </ErrorBoundary>
    </div>
  );
}
