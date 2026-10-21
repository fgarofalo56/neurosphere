import type { ReactElement } from "react";
import { ActionWorkflow } from "./ActionWorkflow";
import { DiffView, ExecutionPanel, Prerequisites, StateBadge } from "./components";
import { STRINGS, orUnknown } from "./strings";
import type { ActionView } from "./types";

/** Read-only facts of an intent plus the workflow controls for its current state. */
export function ActionDetail({
  domainId,
  view,
  onView,
}: {
  readonly domainId: string;
  readonly view: ActionView;
  readonly onView: (view: ActionView) => void;
}): ReactElement {
  const intent = view.intent;
  const D = STRINGS.detail;
  return (
    <article aria-label={STRINGS.detailTitle} data-testid="action-detail">
      <div>
        <code>{intent.action_kind}</code> <StateBadge state={intent.state} />
        {intent.status_reason !== null ? (
          <>
            {" "}
            {D.statusReason}: <code data-testid="status-reason">{intent.status_reason}</code>
          </>
        ) : null}
      </div>
      <dl>
        <dt>{D.target}</dt>
        <dd data-testid="detail-target">{intent.target.canonical_id}</dd>
        <dt>{D.targetVersion}</dt>
        <dd data-testid="detail-version">{orUnknown(intent.target_version)}</dd>
        <dt>{D.diff}</dt>
        <dd>
          <DiffView diff={intent.proposed_diff} />
        </dd>
      </dl>
      <h2>{D.prerequisites}</h2>
      <Prerequisites intent={intent} />
      <h2>{D.execution}</h2>
      <ExecutionPanel execution={view.execution} />
      <ActionWorkflow domainId={domainId} view={view} onView={onView} />
    </article>
  );
}
