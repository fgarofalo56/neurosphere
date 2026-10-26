/**
 * PRP-30 item 4: demo-only mockup gallery. Reached through `/__mockups/<page>/<style>/<mode>` in
 * demo mode only (demo/index.tsx); never routed, never in a production bundle. Static fixture
 * data, no API calls.
 */
import type { ReactElement } from "react";
import { UI_STYLE_IDS, isUiStyleId, type UiStyleId } from "../../../design-system";
import { CostMockup } from "./CostMockup";
import { HomeMockup } from "./HomeMockup";
import { MapMockup } from "./MapMockup";
import type { MockupMode } from "./MockupFrame";

/** Distinctive marker; the production-exclusion test asserts it never reaches a prod build. */
export const MOCKUP_MARKER = "__ns_mockups__";
export const MOCKUP_PATH_PREFIX = "/__mockups/";

export const MOCKUP_PAGES = ["home", "cost-dashboard", "map"] as const;
export type MockupPage = (typeof MOCKUP_PAGES)[number];
export const MOCKUP_MODES: readonly MockupMode[] = ["light", "dark"];

export interface MockupSelection {
  readonly page: MockupPage;
  readonly styleId: UiStyleId;
  readonly mode: MockupMode;
}

/** Parses `/__mockups/<page>/<style>/<mode>`; null when any segment is missing or unknown. */
export function parseMockupPath(pathname: string): MockupSelection | null {
  if (!pathname.startsWith(MOCKUP_PATH_PREFIX)) return null;
  const [page, styleId, mode] = pathname.slice(MOCKUP_PATH_PREFIX.length).split("/");
  const knownPage = MOCKUP_PAGES.find((p) => p === page);
  if (knownPage === undefined || !isUiStyleId(styleId)) return null;
  if (mode !== "light" && mode !== "dark") return null;
  return { page: knownPage, styleId, mode };
}

export function MockupView({ page, styleId, mode }: MockupSelection): ReactElement {
  return (
    <div data-testid="ns-mockup-gallery" data-mockup={MOCKUP_MARKER}>
      {page === "home" ? (
        <HomeMockup styleId={styleId} mode={mode} />
      ) : page === "cost-dashboard" ? (
        <CostMockup styleId={styleId} mode={mode} />
      ) : (
        <MapMockup styleId={styleId} mode={mode} />
      )}
    </div>
  );
}

/** Gallery entry: the selected mockup, or an index of all twelve when the path is incomplete. */
export default function MockupGallery({ pathname }: { readonly pathname: string }): ReactElement {
  const selection = parseMockupPath(pathname);
  if (selection !== null) return <MockupView {...selection} />;
  return (
    <div data-testid="ns-mockup-gallery" data-mockup={MOCKUP_MARKER}>
      <h1>Mockup gallery</h1>
      <ul>
        {MOCKUP_PAGES.flatMap((page) =>
          UI_STYLE_IDS.flatMap((styleId) =>
            MOCKUP_MODES.map((mode) => (
              <li key={`${page}/${styleId}/${mode}`}>
                <a href={`${MOCKUP_PATH_PREFIX}${page}/${styleId}/${mode}`}>
                  {page} / {styleId} / {mode}
                </a>
              </li>
            )),
          ),
        )}
      </ul>
    </div>
  );
}
