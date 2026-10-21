import { Button } from "@fluentui/react-components";
import { useEffect, useId, useState, type ReactElement } from "react";
import { useSearchParams } from "react-router";
import type { ApiError } from "../../api/index.js";
import { DecisionList, MutationError, QueryErrorState, StateBadge, slaText } from "./components";
import { useClaimItem, useDecideItem, useReviewItem, useReviewedIntent } from "./hooks";
import { STRINGS, orUnknown } from "./strings";
import { OPEN_STATES, type Decision, type ReviewItemView } from "./types";

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
  if (query.isPending) return <p aria-busy="true">{D.intentLoading}</p>;
  const { intent, advisory } = query.data;
  return (
    <section aria-label={D.change} data-testid="intent-under-review">
      <h2>{D.change}</h2>
      {advisory ? <p>{D.advisory}</p> : null}
      <dl>
        <dt>{D.target}</dt>
        <dd data-testid="review-target">{intent.target.canonical_id}</dd>
        <dt>{D.version}</dt>
        <dd data-testid="review-version">{intent.target_version}</dd>
        <dt>{D.expires}</dt>
        <dd>{orUnknown(intent.confirmation_expires_at)}</dd>
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
    </section>
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
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<{ error: ApiError; action: Decision | "claim" } | null>(null);
  const claim = useClaimItem();
  const decide = useDecideItem();
  const busy = claim.isPending || decide.isPending;
  const F = STRINGS.form;
  const isMakerChecker = item.kind === "maker_checker";
  const needsHash = isMakerChecker && confirmationHash === null;

  if (!OPEN_STATES.includes(item.state)) {
    return <p data-testid="item-final">{STRINGS.detail.final}</p>;
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
    <div data-testid="item-controls">
      {item.assignee_pseudonym === null ? (
        <p>
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
        </p>
      ) : null}
      <p>
        <label htmlFor={reasonId}>{F.reasonLabel}</label>
        <br />
        <textarea
          id={reasonId}
          rows={3}
          cols={60}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </p>
      {needsHash ? <p>{F.needsHash}</p> : null}
      <Button
        appearance="primary"
        disabled={busy || reason.trim() === "" || needsHash}
        onClick={() => submit("approved")}
      >
        {F.approve}
      </Button>{" "}
      <Button
        disabled={busy || reason.trim() === "" || needsHash}
        onClick={() => submit("rejected")}
      >
        {F.reject}
      </Button>
      {error !== null ? <MutationError error={error.error} action={error.action} /> : null}
    </div>
  );
}

function ItemBody({
  domainId,
  itemId,
}: {
  readonly domainId: string;
  readonly itemId: string;
}): ReactElement {
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
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const item = override ?? query.data;
  const D = STRINGS.detail;
  return (
    <article aria-label={STRINGS.itemTitle} data-testid="review-item">
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
        <dd data-testid="item-sla">{slaText(item.sla_due_at)}</dd>
        <dt>{D.escalation}</dt>
        <dd data-testid="item-escalation">{item.escalation_level}</dd>
        <dt>{D.created}</dt>
        <dd>{item.created_at}</dd>
      </dl>
      {item.kind === "maker_checker" && item.intent_id !== null ? (
        <IntentUnderReview domainId={domainId} intentId={item.intent_id} onHash={setHash} />
      ) : null}
      <h2>{D.decisions}</h2>
      <DecisionList item={item} />
      <ItemControls domainId={domainId} item={item} confirmationHash={hash} onItem={setOverride} />
    </article>
  );
}

export function ReviewItemPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const itemId = params.get("item_id") ?? "";
  return (
    <section aria-label={STRINGS.itemTitle}>
      <h1>{STRINGS.itemTitle}</h1>
      {domainId === "" || itemId === "" ? (
        <p data-testid="domain-required">{STRINGS.itemRequired}</p>
      ) : (
        <ItemBody key={`${domainId}|${itemId}`} domainId={domainId} itemId={itemId} />
      )}
    </section>
  );
}
