import type { ReactElement } from "react";
import { StatusPill, Timestamp } from "../../design-system";
import { EntityLink } from "./explorerParts";
import { EXPLORER_STRINGS } from "./explorerStrings";
import type { CatalogEntityView } from "./explorerTypes";

const S = EXPLORER_STRINGS.entity;

/** Label for a relation type; unknown relations keep their raw machine name. */
export function relationLabel(relationType: string): string {
  return S.relationLabels[relationType] ?? relationType;
}

function limitsText(entity: CatalogEntityView): string {
  const l = entity.limits;
  if (l === undefined) return S.grant.noLimits;
  const parts: string[] = [];
  if (l.tokens_per_minute !== undefined && l.tokens_per_minute !== null)
    parts.push(`${String(l.tokens_per_minute)} tokens/min`);
  if (l.token_quota !== undefined && l.token_quota !== null)
    parts.push(
      `${String(l.token_quota)} tokens per ${l.quota_period === undefined || l.quota_period === null ? "period" : l.quota_period}`,
    );
  if (l.requests_per_minute !== undefined && l.requests_per_minute !== null)
    parts.push(`${String(l.requests_per_minute)} requests/min`);
  if (l.mcp_calls_per_minute !== undefined && l.mcp_calls_per_minute !== null)
    parts.push(`${String(l.mcp_calls_per_minute)} MCP calls/min`);
  return parts.length === 0 ? S.grant.noLimits : parts.join(", ");
}

function GrantRows({ entity }: { readonly entity: CatalogEntityView }): ReactElement {
  const g = S.grant;
  const principal = entity.principal;
  const target = entity.target;
  return (
    <>
      <dt>{g.principal}</dt>
      <dd data-testid="grant-principal">
        {principal === undefined
          ? ""
          : `${principal.display ?? principal.object_id} (${principal.kind})`}
      </dd>
      <dt>{g.target}</dt>
      <dd data-testid="grant-target">
        {target === undefined ? (
          ""
        ) : target.kind === "mcp_server" ? (
          <>
            {target.kind}: <EntityLink id={target.ref} />
          </>
        ) : (
          `${target.kind}: ${target.ref}`
        )}
      </dd>
      <dt>{g.enabled}</dt>
      <dd data-testid="grant-enabled">
        <StatusPill
          label={entity.enabled === true ? g.yes : g.no}
          tone={entity.enabled === true ? "success" : "neutral"}
        />
      </dd>
      <dt>{g.limits}</dt>
      <dd data-testid="grant-limits">{limitsText(entity)}</dd>
      {entity.cost_center === undefined || entity.cost_center === null ? null : (
        <>
          <dt>{g.costCenter}</dt>
          <dd>{entity.cost_center}</dd>
        </>
      )}
      {entity.valid_from === undefined || entity.valid_from === null ? null : (
        <>
          <dt>{g.validFrom}</dt>
          <dd>
            <Timestamp value={entity.valid_from} />
          </dd>
        </>
      )}
      {entity.valid_until === undefined || entity.valid_until === null ? null : (
        <>
          <dt>{g.validUntil}</dt>
          <dd>
            <Timestamp value={entity.valid_until} />
          </dd>
        </>
      )}
    </>
  );
}

function McpRows({ entity }: { readonly entity: CatalogEntityView }): ReactElement {
  const m = S.mcp;
  const tools = entity.tools ?? [];
  return (
    <>
      <dt>{m.url}</dt>
      <dd data-testid="mcp-url">
        <code>{entity.url ?? ""}</code>
      </dd>
      <dt>{m.transport}</dt>
      <dd data-testid="mcp-transport">{entity.transport ?? ""}</dd>
      <dt>{m.auth}</dt>
      <dd data-testid="mcp-auth">{entity.auth?.kind ?? ""}</dd>
      <dt>{m.publishable}</dt>
      <dd>{entity.publishable === true ? S.grant.yes : S.grant.no}</dd>
      <dt>{m.tools}</dt>
      <dd data-testid="mcp-tools">
        {tools.length === 0 ? (
          m.noTools
        ) : (
          <ul>
            {tools.map((t) => (
              <li key={t.name} data-testid="mcp-tool">
                <code>{t.name}</code>
                {t.annotations?.read_only_hint === true ? ` (${m.readOnly})` : ""}
                {t.annotations?.destructive_hint === true ? ` (${m.destructive})` : ""}
              </li>
            ))}
          </ul>
        )}
      </dd>
    </>
  );
}

/** Extra definition rows for the entity types that carry their own fields; others render none. */
export function EntityTypeRows({
  entity,
}: {
  readonly entity: CatalogEntityView;
}): ReactElement | null {
  if (entity.entity_type === "grant") return <GrantRows entity={entity} />;
  if (entity.entity_type === "mcp_server") return <McpRows entity={entity} />;
  return null;
}
