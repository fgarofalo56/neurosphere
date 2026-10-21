import { useId, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { QueryErrorState, StateBadge, slaText } from "./components";
import { useReviewItems } from "./hooks";
import { STRINGS, orUnknown } from "./strings";
import { REVIEW_KINDS, REVIEW_STATES, type ReviewItemState, type ReviewKind } from "./types";

const PAGE_SIZE = 25;

function isKind(value: string): value is ReviewKind {
  return (REVIEW_KINDS as readonly string[]).includes(value);
}

function isState(value: string): value is ReviewItemState {
  return (REVIEW_STATES as readonly string[]).includes(value);
}

export function itemHref(domainId: string, itemId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, item_id: itemId });
  return `/review/item?${p.toString()}`;
}

function QueueBody({
  domainId,
  kind,
  state,
}: {
  readonly domainId: string;
  readonly kind: ReviewKind | "";
  readonly state: ReviewItemState | "";
}): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useReviewItems({ domainId, kind, state, cursor, limit: PAGE_SIZE });
  if (query.isError) {
    return (
      <QueryErrorState
        error={query.error}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const { items, next_cursor: next } = query.data;
  const H = STRINGS.headers;
  return (
    <>
      {items.length === 0 ? (
        <p data-testid="empty-state">{STRINGS.empty}</p>
      ) : (
        <table aria-label={STRINGS.title}>
          <thead>
            <tr>
              <th scope="col">{H.kind}</th>
              <th scope="col">{H.subject}</th>
              <th scope="col">{H.state}</th>
              <th scope="col">{H.assignee}</th>
              <th scope="col">{H.sla}</th>
              <th scope="col">{H.escalation}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.item_id} data-testid="review-row">
                <td>
                  <Link to={itemHref(domainId, item.item_id)}>{item.kind}</Link>
                </td>
                <td>{item.subject_ref}</td>
                <td>
                  <StateBadge state={item.state} />
                </td>
                <td>{item.assignee_pseudonym ?? STRINGS.unassigned}</td>
                <td data-testid="sla-due">{slaText(item.sla_due_at)}</td>
                <td data-testid="escalation-level">{orUnknown(item.escalation_level)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav aria-label="Pagination">
        <button
          type="button"
          disabled={cursors.length <= 1}
          onClick={() => setCursors((c) => c.slice(0, -1))}
        >
          {STRINGS.previousPage}
        </button>{" "}
        <button
          type="button"
          disabled={next === null}
          onClick={() => {
            if (next !== null) setCursors((c) => [...c, next]);
          }}
        >
          {STRINGS.nextPage}
        </button>
      </nav>
    </>
  );
}

export function ReviewQueuePage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const rawKind = params.get("kind") ?? "";
  const rawState = params.get("state") ?? "";
  const kind: ReviewKind | "" = isKind(rawKind) ? rawKind : "";
  const state: ReviewItemState | "" = isState(rawState) ? rawState : "";
  const ids = { domain: useId(), kind: useId(), state: useId() };
  return (
    <section aria-label={STRINGS.title}>
      <h1>{STRINGS.title}</h1>
      <form
        aria-label="Review filters"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const next = new URLSearchParams();
          for (const key of ["domain_id", "kind", "state"] as const) {
            const v = data.get(key);
            if (typeof v === "string" && v.trim() !== "") next.set(key, v.trim());
          }
          setParams(next);
        }}
      >
        <label htmlFor={ids.domain}>{STRINGS.domainLabel}</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <label htmlFor={ids.kind}>{STRINGS.kindLabel}</label>{" "}
        <select id={ids.kind} name="kind" defaultValue={kind}>
          <option value="">{STRINGS.allKinds}</option>
          {REVIEW_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>{" "}
        <label htmlFor={ids.state}>{STRINGS.stateLabel}</label>{" "}
        <select id={ids.state} name="state" defaultValue={state}>
          <option value="">{STRINGS.allStates}</option>
          {REVIEW_STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>{" "}
        <button type="submit">{STRINGS.apply}</button>
      </form>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <QueueBody
          key={`${domainId}|${kind}|${state}`}
          domainId={domainId}
          kind={kind}
          state={state}
        />
      )}
    </section>
  );
}
