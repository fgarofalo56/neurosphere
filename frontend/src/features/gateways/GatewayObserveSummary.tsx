import type { ReactElement } from "react";
import { Link } from "react-router";
import { StatusPill, Timestamp, type StatusTone } from "../../design-system";
import { gatewayDetailHref } from "./paths";
import { STRINGS } from "./strings";
import type { GatewayRegistration, SyncStatus } from "./types";

const O = STRINGS.observe;

const SYNC_TONE: Readonly<Record<SyncStatus, StatusTone>> = {
  ok: "success",
  failed: "danger",
  never: "neutral",
};

function syncLabel(status: SyncStatus): string {
  return status === "ok" ? O.syncOk : status === "failed" ? O.syncFailed : O.syncNever;
}

/** "5 min" style age for the freshness figure; seconds are exact below a minute. */
export function freshnessText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return O.freshnessUnknown;
  if (seconds < 60) return `${String(seconds)} s`;
  if (seconds < 3600) return `${String(Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${String(Math.round(seconds / 3600))} h`;
  return `${String(Math.round(seconds / 86400))} d`;
}

export function coverageText(coverage: number | null | undefined): string {
  return coverage === null || coverage === undefined
    ? O.coverageUnknown
    : `${String(Math.round(coverage * 100))}%`;
}

/** The three log categories; a missing flag is shown as not enabled, never as unknown-ok. */
export function DiagnosticsList({
  gateway,
}: {
  readonly gateway: GatewayRegistration;
}): ReactElement {
  const d = gateway.diagnostics;
  const rows: readonly (readonly [string, boolean])[] = [
    [O.gatewayLogs, d?.gateway_logs === true],
    [O.gatewayLlmLogs, d?.gateway_llm_logs === true],
    [O.gatewayMcpLogs, d?.gateway_mcp_logs === true],
  ];
  return (
    <ul data-testid="gateway-diagnostics" aria-label={O.diagnostics}>
      {rows.map(([name, on]) => (
        <li key={name}>
          {name}:{" "}
          <StatusPill
            label={on ? O.diagnosticsEnabled : O.diagnosticsDisabled}
            tone={on ? "success" : "warning"}
          />
        </li>
      ))}
    </ul>
  );
}

/** Tier, diagnostics, last sync, freshness and coverage of one gateway, plus the detail link. */
export function GatewayObserveSummary({
  domainId,
  gateway,
}: {
  readonly domainId: string;
  readonly gateway: GatewayRegistration;
}): ReactElement {
  const status = gateway.last_sync_status ?? "never";
  return (
    <>
      <dl data-testid="gateway-observe">
        <dt>{O.tier}</dt>
        <dd data-testid="gateway-tier">{gateway.tier}</dd>
        <dt>{O.diagnostics}</dt>
        <dd>
          <DiagnosticsList gateway={gateway} />
        </dd>
        <dt>{O.lastSync}</dt>
        <dd data-testid="gateway-last-sync">
          <StatusPill label={syncLabel(status)} tone={SYNC_TONE[status]} />{" "}
          {gateway.last_sync_at === undefined || gateway.last_sync_at === null ? null : (
            <Timestamp value={gateway.last_sync_at} />
          )}
        </dd>
        <dt>{O.freshness}</dt>
        <dd data-testid="gateway-freshness">{freshnessText(gateway.freshness_seconds)}</dd>
        <dt>{O.coverage}</dt>
        <dd data-testid="gateway-coverage">{coverageText(gateway.coverage)}</dd>
      </dl>
      <p>
        <Link to={gatewayDetailHref(domainId, gateway.id)} data-testid="gateway-detail-link">
          {O.viewInventory}
        </Link>
      </p>
    </>
  );
}
