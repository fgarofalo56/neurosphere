import { Button, makeStyles, tokens } from "@fluentui/react-components";
import { LogoSlot } from "./LogoSlot";
import { NODE_TYPES, NodeTypeIcon } from "./icons";
import { useThemeStore } from "./theme-store";
import { THEME_NAMES, typographyScale } from "./tokens";
import type { ThemeName, TypeScaleName } from "./tokens";

const THEME_LABELS: Readonly<Record<ThemeName, string>> = {
  light: "Light",
  dark: "Dark",
  "high-contrast": "High contrast",
};

/** Foreground/background token pairs shown (and contrast-guarded in tokens.test.ts). */
const SWATCHES = [
  { name: "Primary text", fg: tokens.colorNeutralForeground1, bg: tokens.colorNeutralBackground1 },
  {
    name: "Secondary text",
    fg: tokens.colorNeutralForeground2,
    bg: tokens.colorNeutralBackground1,
  },
  { name: "Brand text", fg: tokens.colorBrandForeground1, bg: tokens.colorNeutralBackground1 },
  { name: "On brand", fg: tokens.colorNeutralForegroundOnBrand, bg: tokens.colorBrandBackground },
] as const;

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalL,
    padding: tokens.spacingHorizontalXL,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
  },
  row: { display: "flex", flexWrap: "wrap", gap: tokens.spacingHorizontalM, alignItems: "center" },
  swatch: {
    padding: tokens.spacingHorizontalM,
    minWidth: "160px",
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke1}`,
  },
});

const TYPE_SAMPLES: readonly TypeScaleName[] = [
  "display",
  "title",
  "subtitle",
  "bodyStrong",
  "body",
  "caption",
];

/** Showcases tokens, type scale, node icons and the logo slot. Used by axe tests and /theme-gallery. */
export function ThemeGallery() {
  const styles = useStyles();
  const themeName = useThemeStore((s) => s.themeName);
  const setTheme = useThemeStore((s) => s.setTheme);
  return (
    <main className={styles.root} aria-labelledby="theme-gallery-heading">
      <h1 id="theme-gallery-heading" style={typographyScale.title}>
        Theme gallery
      </h1>
      <section aria-labelledby="gallery-themes">
        <h2 id="gallery-themes" style={typographyScale.subtitle}>
          Theme
        </h2>
        <div className={styles.row} role="group" aria-label="Theme selection">
          {THEME_NAMES.map((name) => (
            <Button
              key={name}
              appearance={name === themeName ? "primary" : "secondary"}
              aria-pressed={name === themeName}
              onClick={() => {
                setTheme(name);
              }}
            >
              {THEME_LABELS[name]}
            </Button>
          ))}
        </div>
      </section>
      <section aria-labelledby="gallery-colors">
        <h2 id="gallery-colors" style={typographyScale.subtitle}>
          Color pairs
        </h2>
        <div className={styles.row}>
          {SWATCHES.map((s) => (
            <div
              key={s.name}
              className={styles.swatch}
              style={{ color: s.fg, backgroundColor: s.bg }}
            >
              {s.name}
            </div>
          ))}
        </div>
      </section>
      <section aria-labelledby="gallery-type">
        <h2 id="gallery-type" style={typographyScale.subtitle}>
          Typography
        </h2>
        {TYPE_SAMPLES.map((name) => (
          <p key={name} style={{ ...typographyScale[name], margin: 0 }}>
            {name} sample text
          </p>
        ))}
      </section>
      <section aria-labelledby="gallery-nodes">
        <h2 id="gallery-nodes" style={typographyScale.subtitle}>
          Node types
        </h2>
        <div className={styles.row}>
          {NODE_TYPES.map((t) => (
            <NodeTypeIcon key={t} type={t} showLabel />
          ))}
        </div>
      </section>
      <section aria-labelledby="gallery-logo">
        <h2 id="gallery-logo" style={typographyScale.subtitle}>
          Logo slot
        </h2>
        <LogoSlot />
      </section>
    </main>
  );
}
