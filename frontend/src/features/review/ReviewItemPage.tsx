import { Button, Field, Textarea, makeStyles, tokens } from "@fluentui/react-components";
import { useEffect, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import type { ApiError } from "../../api/index.js";
import { useSelectedDomain } from "../../app/domain";
import { EmptyState, LoadingState, PageTemplate, Timestamp } from "../../design-system";
import { Panel } from "../workspaces/Panel";
import { DecisionList, MutationError, QueryErrorState, SlaDue, StateBadge } from "./components";
import { useClaimItem, useDecideItem, useReviewItem, useReviewedIntent } from "./hooks";
import { STRINGS } from "./strings";
import { OPEN_STATES, type Decision, type ReviewItemView } from "./types";

const useStyles = makeStyles({
  article: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalM,
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    columnGap: tokens.spacingHorizontalS,
  },
});

function IntentUnderReview({
  domainId,
  intentId,
  onHash,
}: {
  readonly domainId: string;
  readonly intentId: string;
  readonly onHash: (hash: string | null) => void;
}): ReactElement {
  const query = useReviewedIntent({ domainId, intentId });
  const D = STRINGS.detail;
  // The hash is the one the server issued for this exact intent; it is never recomputed here.
  const serverHash = query.data?.intent.confirmation_hash ?? null;
  useEffect(() => {
    onHash(serverHash);
  }, [serverHash, onHash]);
  if (query.isError) {
    return (
      <QueryErrorState
        error={query.error}
        item
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="intent-loading">
        <LoadingState label={D.intentLoading} rows={3} />
      </div>
    );
  }
  const { intent, advisory } = query.data;
  return (
    <Panel title={D.change} data-testid="intent-under-review">
      {advisory ? <p>{D.advisory}</p> : null}
      <dl>
        <dt>{D.target}</dt>
        <dd data-testid="review-target">{intent.target.canonical_id}</dd>
        <dt>{D.version}</dt>
        <dd data-testid="review-version">{intent.target_version}</dd>
        <dt>{D.expires}</dt>
        <dd>
          {intent.confirmation_expires_at === null ? (
            STRINGS.unknown
          ) : (
            <Timestamp value={intent.confirmation_expires_at} />
          )}
        </dd>
      </dl>
      <ol data-testid="review-diff">
        {intent.proposed_diff.operations.map((op, index) => (
          <li key={`${index}|${op.op}|${op.path}`}>
            <code>{op.op}</code> <code>{op.path}</code>
            {"value" in op ? (
              <>
                {" "}
                <code>{JSON.stringify(op.value)}</code>
              </>
            ) : null}
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function ItemControls({
  domainId,
  item,
  confirmationHash,
  onItem,
}: {
  readonly domainId: string;
  readonly item: ReviewItemView;
  readonly confirmationHash: string | null;
  readonly onItem: (item: ReviewItemView) => void;
}): ReactElement {
  const styles = useStyles();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<{ error: ApiError; action: Decision | "claim" } | null>(null);
  const claim = useClaimItem();
  const decide = useDecideItem();
  const busy = claim.isPending || decide.isPending;
  const F = STRINGS.form;
  const isMakerChecker = item.kind === "maker_checker";
  const needsHash = isMakerChecker && confirmationHash === null;

  if (!OPEN_STATES.includes(item.state)) {
    return (
      <Panel data-testid="item-final">
        <p>{STRINGS.detail.final}</p>
      </Panel>
    );
  }

  const submit = (decision: Decision): void => {
    setError(null);
    decide.mutate(
      {
        domainId,
        itemId: item.item_id,
        decision,
        reason: reason.trim(),
        confirmationHash: isMakerChecker ? (confirmationHash ?? undefined) : undefined,
      },
      {
        onSuccess: (next) => {
          setReason("");
          onItem(next);
        },
        onError: (e) => setError({ error: e, action: decision }),
      },
    );
  };

  return (
    <Panel title={F.title} data-testid="item-controls">
      {item.assignee_pseudonym === null ? (
        <div>
          <Button
            disabled={busy}
            onClick={() => {
              setError(null);
              claim.mutate(
                { domainId, itemId: item.item_id },
                {
                  onSuccess: onItem,
                  onError: (e) => setError({ error: e, action: "claim" }),
                },
              );
            }}
          >
            {claim.isPending ? F.working : F.claim}
          </Button>
        </div>
      ) : null}
      <Field label={F.reasonLabel}>
        <Textarea
          rows={3}
          resize="vertical"
          value={reason}
          onChange={(_e, data) => setReason(data.value)}
        />
      </Field>
      {needsHash ? <p>{F.needsHash}</p> : null}
      <div className={styles.actions}>
        <Button
          appearance="primary"
          disabled={busy || reason.trim() === "" || needsHash}
          onClick={() => submit("approved")}
        >
          {F.approve}
        </Button>
        <Button
          disabled={busy || reason.trim() === "" || needsHash}
          onClick={() => submit("rejected")}
        >
          {F.reject}
        </Button>
      </div>
      {error !== null ? <MutationError error={error.error} action={error.action} /> : null}
    </Panel>
  );
}

function ItemBody({
  domainId,
  itemId,
}: {
  readonly domainId: string;
  readonly itemId: string;
}): ReactElement {
  const styles = useStyles();
  const query = useReviewItem({ domainId, itemId });
  const [override, setOverride] = useState<ReviewItemView | null>(null);
  const [hash, setHash] = useState<string | null>(null);
  if (query.isError) {
    return (
      <QueryErrorState
        error={query.error}
        item
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  const item = override ?? query.data;
  const D = STRINGS.detail;
  return (
    <article aria-label={STRINGS.itemTitle} data-testid="review-item" className={styles.article}>
      <Panel title={D.facts}>
        <dl>
          <dt>{D.kind}</dt>
          <dd>{item.kind}</dd>
          <dt>{D.state}</dt>
          <dd>
            <StateBadge state={item.state} />
          </dd>
          <dt>{D.subject}</dt>
          <dd>{item.subject_ref}</dd>
          <dt>{D.assignee}</dt>
          <dd data-testid="item-assignee">{item.assignee_pseudonym ?? STRINGS.unassigned}</dd>
          <dt>{D.sla}</dt>
          <dd data-testid="item-sla">
            <SlaDue slaDueAt={item.sla_due_at} />
          </dd>
          <dt>{D.escalation}</dt>
          <dd data-testid="item-escalation">{item.escalation_level}</dd>
          <dt>{D.created}</dt>
          <dd>
            <Timestamp value={item.created_at} />
          </dd>
        </dl>
      </Panel>
      {item.kind === "maker_checker" && item.intent_id !== null ? (
        <IntentUnderReview domainId={domainId} intentId={item.intent_id} onHash={setHash} />
      ) : null}
      <Panel title={D.decisions}>
        <DecisionList item={item} />
      </Panel>
      <ItemControls domainId={domainId} item={item} confirmationHash={hash} onItem={setOverride} />
    </article>
  );
}

export function ReviewItemPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const itemId = params.get("item_id") ?? "";
  return (
    <PageTemplate title={STRINGS.itemTitle}>
      {domainId === "" || itemId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.itemRequired} />
        </div>
      ) : (
        <ItemBody key={`${domainId}|${itemId}`} domainId={domainId} itemId={itemId} />
      )}
    </PageTemplate>
  );
}
