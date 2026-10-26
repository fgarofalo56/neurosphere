import {
  Hamburger,
  NavDrawer,
  NavItem as FluentNavItem,
  NavSectionHeader,
  makeStyles,
  mergeClasses,
  tokens,
} from "@fluentui/react-components";
import { useContext, useEffect, useId, useMemo, useRef, useState, type ReactElement } from "react";
import { Outlet, useHref, useLinkClickHandler, useLocation } from "react-router";
import { useRoles } from "../auth";
import {
  LogoSlot,
  NeuroSphereWordmark,
  getThemePack,
  useThemeStore,
  useUiStyle,
} from "../design-system";
import { CopilotDock } from "../features/copilot/CopilotDock";
import { SandboxBanner } from "../features/sandbox/SandboxBanner";
import { ConfigContext } from "./ConfigContext";
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

const NAV_WIDTH_OPS = "184px";
const NAV_WIDTH_ENTERPRISE = "248px";
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
  // Ops console: slim, dark-leaning, instrument-panel header (docs/design/prp-30 mockups).
  headerOps: {
    minHeight: "40px",
    paddingBlock: tokens.spacingVerticalXXS,
    paddingInline: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  // Enterprise Fluent: taller, branded top edge, soft elevation.
  headerEnterprise: {
    minHeight: "56px",
    paddingInline: tokens.spacingHorizontalXL,
    borderTop: `3px solid ${tokens.colorBrandBackground}`,
    boxShadow: tokens.shadow4,
    position: "relative",
    zIndex: 1,
  },
  logo: { maxHeight: "32px", maxWidth: "160px" },
  live: {
    display: "inline-flex",
    alignItems: "center",
    columnGap: "6px",
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: "11px",
    color: tokens.colorNeutralForeground2,
    paddingInline: tokens.spacingHorizontalS,
    paddingBlock: "2px",
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusSmall,
  },
  liveDot: { width: "7px", height: "7px", borderRadius: "50%", flexShrink: 0 },
  spacer: { flexGrow: 1 },
  body: { display: "flex", flexGrow: 1, minHeight: 0 },
  nav: { flexShrink: 0 },
  navOps: { width: NAV_WIDTH_OPS, backgroundColor: tokens.colorNeutralBackground2 },
  navEnterprise: { width: NAV_WIDTH_ENTERPRISE },
  itemOps: { minHeight: "28px", fontSize: tokens.fontSizeBase200 },
  itemEnterprise: { minHeight: "36px" },
  sectionOps: {
    fontSize: "10px",
    textTransform: "uppercase",
    letterSpacing: "0.1em",
  },
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
    ":focus": { outlineStyle: "none" },
  },
  mainOps: {
    paddingBlock: "14px",
    paddingInline: "16px",
    backgroundColor: tokens.colorNeutralBackground3,
  },
  mainEnterprise: {
    paddingBlock: tokens.spacingVerticalXXL,
    paddingInline: tokens.spacingHorizontalXXXL,
    // Background1, not the mockups' Background2 canvas: pages not yet restyled (PRP-30 items 6-8)
    // carry brand-tint text that is 4.34:1 on #fafafa. Move to Background2 once they use the
    // primitives.
    backgroundColor: tokens.colorNeutralBackground1,
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
  const styles = useStyles();
  const { id: styleId } = useUiStyle();
  const to = withDomain(item.to, domainId);
  const href = useHref(to);
  const handleClick = useLinkClickHandler(to);
  return (
    <FluentNavItem
      as="a"
      href={href}
      value={item.to}
      className={styleId === "ops-console" ? styles.itemOps : styles.itemEnterprise}
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
  const { id: styleId } = useUiStyle();
  const ops = styleId === "ops-console";
  const idBase = useId();
  const { pathname } = useLocation();
  const { domainId } = useSelectedDomain();
  const selected = selectedNavTo(allItems, pathname);
  return (
    <NavDrawer
      aria-label="Primary"
      data-slot="navigation"
      className={
        compact ? undefined : mergeClasses(styles.nav, ops ? styles.navOps : styles.navEnterprise)
      }
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
              <NavSectionHeader
                id={headingId}
                role="presentation"
                className={ops ? styles.sectionOps : undefined}
              >
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

/** The active theme pack's header logo beside the mark; nothing at all when the pack ships none. */
function HeaderLogo(): ReactElement | null {
  const styles = useStyles();
  const packId = useThemeStore((s) => s.packId);
  const { asset, altText } = getThemePack(packId).logos.header;
  if (asset === null) return null;
  return (
    <LogoSlot>
      <img src={asset.src} alt={altText} className={styles.logo} />
    </LogoSlot>
  );
}

/**
 * Ops-style "LIVE" label. Static: it carries no freshness figure and fetches nothing, so the
 * request set is identical in every UI style (presentation only).
 */
function LiveIndicator(): ReactElement | null {
  const styles = useStyles();
  const { treatment, health } = useUiStyle();
  if (!treatment.liveIndicator) return null;
  return (
    <span className={styles.live} data-slot="live-indicator">
      <span
        className={styles.liveDot}
        style={{ backgroundColor: health.ok.icon, boxShadow: `0 0 6px 2px ${health.ok.icon}` }}
        aria-hidden="true"
      />
      LIVE
    </span>
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
  const config = useContext(ConfigContext);
  const applyDeploymentDefault = useThemeStore((s) => s.applyDeploymentDefault);
  const defaultThemePack = config?.defaultThemePack;
  const defaultThemeMode = config?.defaultThemeMode;
  const defaultUiStyle = config?.defaultUiStyle;
  const { id: styleId } = useUiStyle();
  const ops = styleId === "ops-console";

  // Deployment default theme from runtime config; a saved user choice wins inside the store.
  useEffect(() => {
    applyDeploymentDefault({
      ...(defaultThemePack === undefined ? {} : { packId: defaultThemePack }),
      ...(defaultThemeMode === undefined ? {} : { themeName: defaultThemeMode }),
      ...(defaultUiStyle === undefined ? {} : { styleId: defaultUiStyle }),
    });
  }, [applyDeploymentDefault, defaultThemePack, defaultThemeMode, defaultUiStyle]);

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
      <header
        className={mergeClasses(styles.header, ops ? styles.headerOps : styles.headerEnterprise)}
      >
        {compact ? (
          <Hamburger aria-label="Open navigation" onClick={() => setNavOpen(true)} />
        ) : null}
        <NeuroSphereWordmark size={ops ? 22 : 28} />
        <HeaderLogo />
        <span className={styles.spacer} />
        <LiveIndicator />
        <DomainSwitcher />
        <UserMenu />
      </header>
      <SandboxBanner />
      <div className={styles.body}>
        <ShellNav
          sections={sections}
          allItems={visible}
          compact={compact}
          navOpen={navOpen}
          setNavOpen={setNavOpen}
        />
        <main
          id={MAIN_ID}
          ref={mainRef}
          tabIndex={-1}
          className={mergeClasses(styles.main, ops ? styles.mainOps : styles.mainEnterprise)}
        >
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
