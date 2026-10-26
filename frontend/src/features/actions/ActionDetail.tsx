import { makeStyles, tokens } from "@fluentui/react-components";
import type { ReactElement } from "react";
import { ActionWorkflow } from "./ActionWorkflow";
import { DiffView, ExecutionPanel, Prerequisites, StateBadge } from "./components";
import { STRINGS, orUnknown } from "./strings";
import type { ActionView } from "./types";
import { Panel } from "../../design-system";

const useStyles = makeStyles({
  article: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
  },
  header: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXS,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
  },
});

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
  const styles = useStyles();
  const intent = view.intent;
  const D = STRINGS.detail;
  return (
    <article
      aria-label={STRINGS.detailTitle}
      data-testid="action-detail"
      className={styles.article}
    >
      <div className={styles.header}>
        <code>{intent.action_kind}</code> <StateBadge state={intent.state} />
        {intent.status_reason !== null ? (
          <span>
            {D.statusReason}: <code data-testid="status-reason">{intent.status_reason}</code>
          </span>
        ) : null}
      </div>
      <div className={styles.grid}>
        <Panel title={D.summary}>
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
        </Panel>
        <Panel title={D.prerequisites}>
          <Prerequisites intent={intent} />
        </Panel>
        <Panel title={D.execution}>
          <ExecutionPanel execution={view.execution} />
        </Panel>
      </div>
      <ActionWorkflow domainId={domainId} view={view} onView={onView} />
    </article>
  );
}
