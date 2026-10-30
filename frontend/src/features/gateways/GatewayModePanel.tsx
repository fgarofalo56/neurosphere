import { Button, MessageBar, MessageBarBody, MessageBarTitle } from "@fluentui/react-components";
import { useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { Panel, StatusPill, Timestamp } from "../../design-system";
import type { ApiError } from "../../api/index.js";
import { useDraftModeChange } from "./hooks";
import { canPropose } from "./permissions";
import { gatewayRefusalText } from "./refusals";
import { STRINGS } from "./strings";
import type { ActionView, GatewayMode, GatewayRegistration, ModePreflight } from "./types";

/** App route (not API) of one action intent, the existing approval flow's detail page. */
export function actionDetailHref(domainId: string, intentId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, intent_id: intentId });
  return `/actions/detail?${p.toString()}`;
}

function otherMode(mode: GatewayMode): GatewayMode {
  return mode === "manage" ? "observe" : "manage";
}

export function PreflightResult({
  preflight,
}: {
  readonly preflight: ModePreflight | null;
}): ReactElement {
  const P = STRINGS.preflight;
  if (preflight === null) return <p data-testid="preflight-none">{P.none}</p>;
  const missing = preflight.missing ?? [];
  return (
    <div data-testid="preflight">
      <p>
        <span data-testid="preflight-status">
          <StatusPill
            label={preflight.passed ? P.passed : P.failed}
            tone={preflight.passed ? "success" : "danger"}
          />
        </span>{" "}
        {P.checkedAt}: <Timestamp value={preflight.checked_at} />
      </p>
      {!preflight.passed ? <p>{P.failedHelp}</p> : null}
      <dl>
        <dt>{P.required}</dt>
        <dd>
          <ul aria-label={P.required} data-testid="preflight-required">
            {preflight.required.map((action) => (
              <li key={action}>
                <code>{action}</code>
              </li>
            ))}
          </ul>
        </dd>
        <dt>{P.missing}</dt>
        <dd>
          {missing.length === 0 ? (
            <span data-testid="preflight-none-missing">{P.noneMissing}</span>
          ) : (
            <ul aria-label={P.missing} data-testid="preflight-missing">
              {missing.map((action) => (
                <li key={action}>
                  <code>{action}</code>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </div>
  );
}

/**
 * One gateway's audited mode switch. The button DRAFTS a `gateway_mode_change` action intent
 * through the mode route and then links to the approval flow; it never flips the mode itself.
 * The draft control is disabled without `action.propose` in the domain (usability only: the API
 * decides) and, for a Government gateway, with the capability reason.
 */
export function GatewayModePanel({
  domainId,
  gateway,
}: {
  readonly domainId: string;
  readonly gateway: GatewayRegistration;
}): ReactElement {
  const { domains } = useSelectedDomain();
  const draft = useDraftModeChange();
  const [drafted, setDrafted] = useState<ActionView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const target = otherMode(gateway.mode);
  // One key per (gateway, target mode, revision): a retried click replays the same draft.
  const idempotencyKey = useMemo(
    () => `button-mode-${crypto.randomUUID()}`,
    [gateway.id, target, gateway.mode_revision],
  );
  const S = STRINGS.switch;
  const M = STRINGS.mode;
  const proposeAllowed = canPropose(domains, domainId);
  const governmentBlocked = target === "manage" && gateway.cloud === "government";
  const disabled = !proposeAllowed || governmentBlocked || draft.isPending;
  return (
    <Panel title={gateway.name} testId="gateway-panel">
      <dl>
        <dt>{M.label}</dt>
        <dd data-testid="gateway-mode">
          <StatusPill
            label={gateway.mode === "manage" ? M.manage : M.observe}
            tone={gateway.mode === "manage" ? "warning" : "info"}
          />
        </dd>
        <dt>{M.changedBy}</dt>
        <dd data-testid="gateway-changed-by">
          {gateway.mode_changed_by === null ? M.neverChanged : gateway.mode_changed_by}
        </dd>
        <dt>{M.changedAt}</dt>
        <dd data-testid="gateway-changed-at">
          <Timestamp value={gateway.mode_changed_at} />
        </dd>
        <dt>{M.revision}</dt>
        <dd>{gateway.mode_revision}</dd>
      </dl>
      <h3>{STRINGS.preflight.title}</h3>
      <PreflightResult preflight={gateway.preflight} />
      {gateway.mode === "observe" ? <p data-testid="observe-note">{S.observeNote}</p> : null}
      {!proposeAllowed ? <p data-testid="no-permission">{S.noPermission}</p> : null}
      {governmentBlocked ? <p data-testid="government-blocked">{S.government}</p> : null}
      <div>
        <Button
          appearance="primary"
          disabled={disabled}
          onClick={() => {
            setError(null);
            draft.mutate(
              {
                domainId,
                gatewayId: gateway.id,
                request: { mode: target, idempotency_key: idempotencyKey, channel: "button" },
              },
              { onSuccess: setDrafted, onError: setError },
            );
          }}
        >
          {draft.isPending ? S.working : target === "manage" ? S.toManage : S.toObserve}
        </Button>
      </div>
      {error !== null ? (
        <MessageBar intent="error" role="alert" data-testid="mode-refusal">
          <MessageBarBody>
            <MessageBarTitle>{STRINGS.refusals.title}</MessageBarTitle>
            {gatewayRefusalText(error)}
            {error.problem?.reason !== undefined ? (
              <>
                {" "}
                (<code data-testid="mode-refusal-reason">{error.problem.reason}</code>)
              </>
            ) : null}
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {drafted !== null ? (
        <MessageBar intent="success" role="status" data-testid="mode-drafted">
          <MessageBarBody>
            <MessageBarTitle>{S.drafted}</MessageBarTitle>
            {S.draftedDetail}{" "}
            <Link to={actionDetailHref(domainId, drafted.intent.intent_id)}>{S.openApproval}</Link>
          </MessageBarBody>
        </MessageBar>
      ) : null}
    </Panel>
  );
}
