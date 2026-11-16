import { createQueryHook } from "../../api/index.js";
import { bundlePath, frameworksPath } from "./paths";

/**
 * Response shapes of the compliance read API (services/api compliance/). Metadata only: the
 * bundle maps what was observed to framework controls and carries no verdict or score. Unknown
 * counts arrive as null and are shown as the word "unknown", never 0.
 */
export interface FrameworkSummary {
  readonly framework_id: string;
  readonly title: string;
  readonly framework_version: string;
  readonly source_url: string;
  readonly source_retrieved: string;
  readonly control_count: number;
}

export interface FrameworkList {
  readonly library_version: string;
  readonly frameworks: readonly FrameworkSummary[];
}

export type SupportStatus =
  "designed" | "implemented_tested" | "inherited" | "customer" | "planned" | "not_applicable";

export type SummaryWord =
  "evidence_present" | "evidence_partial" | "no_evidence" | "customer_responsibility";

export type ObservationStatus = "observed" | "partial" | "unavailable" | "not_collected";

export interface Control {
  readonly control_id: string;
  readonly framework_id: string;
  readonly title: string;
  readonly source_url: string;
  readonly source_retrieved: string;
  readonly framework_version: string;
}

export interface ControlSummary {
  readonly control: Control;
  readonly support_status: SupportStatus;
  readonly evidence_sources: readonly string[];
  readonly summary: SummaryWord;
}

export interface Measure {
  readonly name: string;
  readonly value: number | null;
}

export interface Observation {
  readonly source_id: string;
  readonly status: ObservationStatus;
  readonly reason_code: string | null;
  readonly window_start: string;
  readonly window_end: string;
  readonly latest_at: string | null;
  readonly truncated: boolean;
  readonly measures: readonly Measure[];
}

export interface EvidenceBundle {
  readonly framework_id: string;
  readonly framework_version: string;
  readonly library_version: string;
  readonly domain_id: string;
  readonly generated_at: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly controls: readonly ControlSummary[];
  readonly observations: readonly Observation[];
  readonly digest: string;
}

export const useFrameworks = createQueryHook<Record<string, never>, FrameworkList>({
  key: "compliance-frameworks",
  fetcher: (client, _p, signal) => client.get<FrameworkList>(frameworksPath(), undefined, signal),
});

export interface BundleParams {
  readonly domainId: string;
  readonly frameworkId: string;
}

export const useBundle = createQueryHook<BundleParams, EvidenceBundle>({
  key: "compliance-bundle",
  fetcher: (client, p, signal) =>
    client.get<EvidenceBundle>(bundlePath(p.domainId), { framework_id: p.frameworkId }, signal),
});

/** Display count: unknown (null) is the word, never 0. */
export function countText(value: number | null, unknownWord: string): string {
  return value === null ? unknownWord : String(value);
}

/** Save the bundle exactly as the API returned it. No token is placed in a URL. */
export function downloadBundle(bundle: EvidenceBundle): void {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `evidence-${bundle.framework_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
