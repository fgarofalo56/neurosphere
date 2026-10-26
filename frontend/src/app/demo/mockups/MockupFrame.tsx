import {
  Avatar,
  Badge,
  Button,
  FluentProvider,
  Input,
  makeStaticStyles,
  makeStyles,
  mergeClasses,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import { useMemo, type ReactElement, type ReactNode } from "react";
import {
  NeuroSphereWordmark,
  UiStyleContext,
  getThemePack,
  getUiStyle,
  resolveStyledTheme,
  resolveUiStyle,
  useUiStyle,
  type UiStyleId,
} from "../../../design-system";
import { NAV_SAMPLE } from "./fixtures";

export type MockupMode = "light" | "dark";

/** The gallery owns the whole page: no default body margin around the mock app chrome. */
const useBodyReset = makeStaticStyles("body { margin: 0; }");

const useStyles = makeStyles({
  provider: { minHeight: "100vh", display: "flex", flexDirection: "column" },
  shell: {
    flexGrow: 1,
    display: "grid",
    gridTemplateColumns: "auto 1fr",
    gridTemplateRows: "auto 1fr",
    gridTemplateAreas: '"header header" "nav main"',
    minHeight: "100vh",
  },
  header: {
    gridArea: "header",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalL,
    boxSizing: "border-box",
    color: tokens.colorNeutralForeground1,
  },
  headerOps: {
    height: "40px",
    paddingInline: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground2,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
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
  liveDot: {
    width: "7px",
    height: "7px",
    borderRadius: "50%",
    flexShrink: 0,
  },
  headerEnterprise: {
    height: "56px",
    paddingInline: tokens.spacingHorizontalXL,
    backgroundColor: tokens.colorNeutralBackground1,
    borderTop: `3px solid ${tokens.colorBrandBackground}`,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    position: "relative",
    zIndex: 1,
  },
  headerLeft: { display: "flex", alignItems: "center", columnGap: tokens.spacingHorizontalL },
  headerRight: { display: "flex", alignItems: "center", columnGap: tokens.spacingHorizontalS },
  divider: {
    width: "1px",
    height: "20px",
    backgroundColor: tokens.colorNeutralStroke2,
  },
  context: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
  },
  search: { width: "260px" },
  nav: {
    gridArea: "nav",
    boxSizing: "border-box",
    overflow: "hidden",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRight: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  navOps: {
    width: "184px",
    paddingBlock: tokens.spacingVerticalS,
    paddingInline: "6px",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  navEnterprise: {
    width: "248px",
    paddingBlock: tokens.spacingVerticalL,
    paddingInline: tokens.spacingHorizontalM,
  },
  navList: { listStyle: "none", margin: 0, padding: 0 },
  groupLabel: {
    margin: 0,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightSemibold,
  },
  groupLabelOps: {
    paddingBlock: "10px 2px",
    paddingInline: tokens.spacingHorizontalS,
    fontSize: "10px",
    textTransform: "uppercase",
    letterSpacing: "0.1em",
  },
  groupLabelEnterprise: {
    paddingBlock: "14px 4px",
    paddingInline: tokens.spacingHorizontalS,
    fontSize: tokens.fontSizeBase200,
  },
  navButton: {
    width: "100%",
    justifyContent: "flex-start",
    textAlign: "start",
    borderRadius: tokens.borderRadiusMedium,
  },
  navButtonOps: { minHeight: "26px", fontSize: tokens.fontSizeBase200 },
  navButtonEnterprise: { minHeight: "36px" },
  navActiveOps: {
    backgroundColor: tokens.colorNeutralBackground3,
    boxShadow: `inset 2px 0 0 ${tokens.colorBrandBackground}`,
    fontWeight: tokens.fontWeightSemibold,
  },
  navActiveEnterprise: {
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: `inset 3px 0 0 ${tokens.colorBrandBackground}, ${tokens.shadow4}`,
    fontWeight: tokens.fontWeightSemibold,
  },
  main: {
    gridArea: "main",
    minWidth: 0,
    boxSizing: "border-box",
    color: tokens.colorNeutralForeground1,
  },
  mainOps: {
    padding: "14px 16px 24px",
    backgroundColor: tokens.colorNeutralBackground3,
  },
  mainEnterprise: {
    padding: "28px 40px 40px",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  panel: {
    minWidth: 0,
    boxSizing: "border-box",
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    display: "flex",
    flexDirection: "column",
  },
  panelCompact: { padding: "12px", rowGap: tokens.spacingVerticalS },
  panelLifted: { backgroundColor: tokens.colorNeutralBackground2 },
  panelComfortable: { padding: tokens.spacingHorizontalL, rowGap: tokens.spacingVerticalM },
  panelRaised: { boxShadow: tokens.shadow4 },
  panelStrong: { ...shorthands.borderColor(tokens.colorNeutralStroke1) },
  panelSmall: { borderRadius: tokens.borderRadiusSmall },
  panelMedium: { borderRadius: tokens.borderRadiusLarge },
  panelHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    columnGap: tokens.spacingHorizontalM,
  },
  panelTitle: {
    margin: 0,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  panelTitleOps: {
    fontSize: tokens.fontSizeBase200,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  panelTitleEnterprise: { fontSize: tokens.fontSizeBase400 },
  panelNote: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground2 },
});

export interface MockupFrameProps {
  readonly styleId: UiStyleId;
  readonly mode: MockupMode;
  /** Label of the nav item shown as active. */
  readonly active: string;
  readonly children: ReactNode;
}

/** Theme + style provider for one style x mode, plus a static mock of the app chrome. */
export function MockupFrame({ styleId, mode, active, children }: MockupFrameProps): ReactElement {
  const styles = useStyles();
  useBodyReset();
  const style = getUiStyle(styleId);
  const theme = useMemo(
    () => resolveStyledTheme(getThemePack("default"), mode, style),
    [mode, style],
  );
  const uiStyle = useMemo(() => resolveUiStyle(style, mode), [mode, style]);
  return (
    <FluentProvider
      theme={theme}
      className={styles.provider}
      data-theme={mode}
      data-ui-style={styleId}
    >
      <UiStyleContext.Provider value={uiStyle}>
        <div className={styles.shell}>
          <Header />
          <Nav active={active} />
          <main
            className={mergeClasses(
              styles.main,
              uiStyle.id === "ops-console" ? styles.mainOps : styles.mainEnterprise,
            )}
          >
            {children}
          </main>
        </div>
      </UiStyleContext.Provider>
    </FluentProvider>
  );
}

function Header(): ReactElement {
  const styles = useStyles();
  const { id, treatment, health } = useUiStyle();
  const ops = id === "ops-console";
  return (
    <header
      className={mergeClasses(styles.header, ops ? styles.headerOps : styles.headerEnterprise)}
    >
      <div className={styles.headerLeft}>
        <NeuroSphereWordmark size={ops ? 22 : 28} />
        <span className={styles.divider} aria-hidden="true" />
        <span className={styles.context}>Domain: contoso-prod (Azure Commercial)</span>
      </div>
      <div className={styles.headerRight}>
        {treatment.liveIndicator ? (
          <span className={styles.live} data-slot="live-indicator">
            <span
              className={styles.liveDot}
              style={{
                backgroundColor: health.ok.icon,
                boxShadow: `0 0 6px 2px ${health.ok.icon}`,
              }}
              aria-hidden="true"
            />
            LIVE &middot; data 38s old
          </span>
        ) : null}
        <Input
          className={styles.search}
          size={ops ? "small" : "medium"}
          placeholder="Search agents, models, reports"
          aria-label="Search"
          readOnly
        />
        <Badge appearance="tint" color="informative" size={ops ? "small" : "medium"}>
          Reviewer
        </Badge>
        <Avatar name="Frank Garofalo" size={ops ? 24 : 32} color="brand" />
      </div>
    </header>
  );
}

function Nav({ active }: { readonly active: string }): ReactElement {
  const styles = useStyles();
  const { id } = useUiStyle();
  const ops = id === "ops-console";
  return (
    <nav
      aria-label="Primary"
      className={mergeClasses(styles.nav, ops ? styles.navOps : styles.navEnterprise)}
    >
      {NAV_SAMPLE.map((section) => (
        <div key={section.group}>
          <p
            className={mergeClasses(
              styles.groupLabel,
              ops ? styles.groupLabelOps : styles.groupLabelEnterprise,
            )}
          >
            {section.group}
          </p>
          <ul className={styles.navList}>
            {section.items.map((item) => (
              <li key={item}>
                <Button
                  appearance="subtle"
                  size={ops ? "small" : "medium"}
                  aria-current={item === active ? "page" : undefined}
                  className={mergeClasses(
                    styles.navButton,
                    ops ? styles.navButtonOps : styles.navButtonEnterprise,
                    item === active && (ops ? styles.navActiveOps : styles.navActiveEnterprise),
                  )}
                >
                  {item}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export interface PanelProps {
  readonly title: string;
  readonly note?: ReactNode;
  readonly children: ReactNode;
}

/** A card surface whose density, border and elevation follow the active UI style. */
export function Panel({ title, note, children }: PanelProps): ReactElement {
  const styles = useStyles();
  const { density, treatment, id } = useUiStyle();
  return (
    <section
      aria-label={title}
      className={mergeClasses(
        styles.panel,
        density === "compact" ? styles.panelCompact : styles.panelComfortable,
        treatment.surface === "raised" && styles.panelRaised,
        treatment.panelSurface === "lifted" && styles.panelLifted,
        treatment.border === "strong" && styles.panelStrong,
        treatment.radius === "small" ? styles.panelSmall : styles.panelMedium,
      )}
    >
      <div className={styles.panelHead}>
        <h2
          className={mergeClasses(
            styles.panelTitle,
            id === "ops-console" ? styles.panelTitleOps : styles.panelTitleEnterprise,
          )}
        >
          {title}
        </h2>
        {note === undefined ? null : <span className={styles.panelNote}>{note}</span>}
      </div>
      {children}
    </section>
  );
}
