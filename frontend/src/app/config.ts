/** Runtime configuration (C7): fetched from /config.json at startup, validated by hand. */

import { isThemeName, isThemePackId } from "../design-system/theme-store";
import type { ThemeName } from "../design-system/tokens";

export const CLOUDS = ["commercial", "government"] as const;
export type Cloud = (typeof CLOUDS)[number];

export interface AppConfig {
  readonly cloud: Cloud;
  readonly tenantId: string;
  readonly clientId: string;
  readonly apiBaseUrl: string;
  readonly apiScope: string;
  /** Deployment default theme pack id. Presentation only; a user's saved choice wins. */
  readonly defaultThemePack?: string;
  /** Deployment default theme mode. Presentation only; a user's saved choice wins. */
  readonly defaultThemeMode?: ThemeName;
}

export class ConfigError extends Error {
  readonly problems: readonly string[];

  constructor(problems: readonly string[]) {
    super(`Invalid application configuration: ${problems.join("; ")}`);
    this.name = "ConfigError";
    this.problems = problems;
  }
}

const STRING_FIELDS = ["tenantId", "clientId", "apiBaseUrl", "apiScope"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCloud(value: unknown): value is Cloud {
  return typeof value === "string" && (CLOUDS as readonly string[]).includes(value);
}

/** Validates an untrusted value into an AppConfig, or throws ConfigError listing every problem. */
export function parseConfig(raw: unknown): AppConfig {
  if (!isRecord(raw)) throw new ConfigError(["config must be a JSON object"]);
  const problems: string[] = [];

  if (raw["cloud"] === undefined) {
    problems.push('"cloud" is required (commercial or government)');
  } else if (!isCloud(raw["cloud"])) {
    problems.push('"cloud" must be "commercial" or "government"');
  }

  const strings: Record<string, string> = {};
  for (const field of STRING_FIELDS) {
    const value = raw[field];
    if (typeof value !== "string" || value.trim() === "") {
      problems.push(`"${field}" must be a non-empty string`);
    } else {
      strings[field] = value.trim();
    }
  }

  const themePack = raw["defaultThemePack"];
  if (themePack !== undefined && !isThemePackId(themePack)) {
    problems.push('"defaultThemePack" must be the id of a known theme pack');
  }
  const themeMode = raw["defaultThemeMode"];
  if (themeMode !== undefined && !isThemeName(themeMode)) {
    problems.push('"defaultThemeMode" must be "light", "dark" or "high-contrast"');
  }

  const cloud = raw["cloud"];
  if (problems.length > 0 || !isCloud(cloud)) throw new ConfigError(problems);

  return {
    cloud,
    tenantId: strings["tenantId"] ?? "",
    clientId: strings["clientId"] ?? "",
    apiBaseUrl: strings["apiBaseUrl"] ?? "",
    apiScope: strings["apiScope"] ?? "",
    ...(isThemePackId(themePack) ? { defaultThemePack: themePack } : {}),
    ...(isThemeName(themeMode) ? { defaultThemeMode: themeMode } : {}),
  };
}

/** Local-dev defaults from VITE_NS_* (non-secret). Only used when running the dev server. */
export function devDefaults(
  env: Record<string, unknown> = import.meta.env,
): Record<string, unknown> {
  if (env["DEV"] !== true) return {};
  const map: Record<string, string> = {
    cloud: "VITE_NS_CLOUD",
    tenantId: "VITE_NS_TENANT_ID",
    clientId: "VITE_NS_CLIENT_ID",
    apiBaseUrl: "VITE_NS_API_BASE_URL",
    apiScope: "VITE_NS_API_SCOPE",
  };
  const out: Record<string, unknown> = {};
  for (const [field, key] of Object.entries(map)) {
    const value = env[key];
    if (typeof value === "string" && value !== "") out[field] = value;
  }
  return out;
}

export type FetchLike = (input: string) => Promise<Pick<Response, "ok" | "status" | "json">>;

/** Fetches and validates config.json; file values win over dev defaults. */
export async function loadConfig(
  fetchImpl: FetchLike = (input) => fetch(input, { cache: "no-store" }),
  url = "/config.json",
  defaults: Record<string, unknown> = devDefaults(),
): Promise<AppConfig> {
  let body: unknown;
  try {
    const response = await fetchImpl(url);
    if (!response.ok) throw new ConfigError([`${url} returned HTTP ${response.status}`]);
    body = await response.json();
  } catch (error) {
    if (error instanceof ConfigError) throw error;
    throw new ConfigError([`${url} could not be loaded or is not valid JSON`]);
  }
  if (!isRecord(body)) throw new ConfigError(["config must be a JSON object"]);
  return parseConfig({ ...defaults, ...body });
}
