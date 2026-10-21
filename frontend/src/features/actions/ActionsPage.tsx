import { useId, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { ActionDetail } from "./ActionDetail";
import { EmergencyBanner, QueryErrorState, StateBadge } from "./components";
import { useAction, useActionList } from "./hooks";
import { STRINGS } from "./strings";
import { ACTION_STATES, type ActionState, type ActionView } from "./types";

const PAGE_SIZE = 25;

function isState(value: string): value is ActionState {
  return (ACTION_STATES as readonly string[]).includes(value);
}

export function detailHref(domainId: string, intentId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, intent_id: intentId });
  return `/actions/detail?${p.toString()}`;
}

export function proposeHref(domainId: string): string {
  return domainId === ""
    ? "/actions/propose"
    : `/actions/propose?${new URLSearchParams({ domain_id: domainId }).toString()}`;
}

function ListBody({
  domainId,
  state,
}: {
  readonly domainId: string;
  readonly state: ActionState | "";
}): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useActionList({ domainId, state, cursor, limit: PAGE_SIZE });
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
              <th scope="col">{H.target}</th>
              <th scope="col">{H.state}</th>
              <th scope="col">{H.channel}</th>
              <th scope="col">{H.created}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((v) => (
              <tr key={v.intent.intent_id} data-testid="action-row">
                <td>
                  <Link to={detailHref(domainId, v.intent.intent_id)}>{v.intent.action_kind}</Link>
                  {v.advisory ? " (advisory)" : ""}
                </td>
                <td>{v.intent.target.canonical_id}</td>
                <td>
                  <StateBadge state={v.intent.state} />
                </td>
                <td>{v.intent.channel}</td>
                <td>{v.intent.created_at}</td>
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

export function ActionsPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const rawState = params.get("state") ?? "";
  const state: ActionState | "" = isState(rawState) ? rawState : "";
  const ids = { domain: useId(), state: useId() };
  return (
    <section aria-label={STRINGS.title}>
      <h1>{STRINGS.title}</h1>
      <EmergencyBanner />
      <form
        aria-label="Action filters"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const next = new URLSearchParams();
          for (const key of ["domain_id", "state"] as const) {
            const v = data.get(key);
            if (typeof v === "string" && v.trim() !== "") next.set(key, v.trim());
          }
          setParams(next);
        }}
      >
        <label htmlFor={ids.domain}>{STRINGS.domainLabel}</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <label htmlFor={ids.state}>{STRINGS.stateLabel}</label>{" "}
        <select id={ids.state} name="state" defaultValue={state}>
          <option value="">{STRINGS.allStates}</option>
          {ACTION_STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>{" "}
        <button type="submit">{STRINGS.apply}</button>
      </form>
      <p>
        <Link to={proposeHref(domainId)}>{STRINGS.proposeLink}</Link>
      </p>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <ListBody key={`${domainId}|${state}`} domainId={domainId} state={state} />
      )}
    </section>
  );
}

function DetailBody({
  domainId,
  intentId,
}: {
  readonly domainId: string;
  readonly intentId: string;
}): ReactElement {
  const query = useAction({ domainId, intentId });
  // The latest answer from a workflow step wins until the user refreshes from the server.
  const [override, setOverride] = useState<ActionView | null>(null);
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
  const view = override ?? query.data;
  return (
    <>
      <p>
        <button
          type="button"
          onClick={() => {
            void query.refetch().then(() => setOverride(null));
          }}
        >
          {STRINGS.refresh}
        </button>
      </p>
      <ActionDetail domainId={domainId} view={view} onView={setOverride} />
    </>
  );
}

export function ActionDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const intentId = params.get("intent_id") ?? "";
  return (
    <section aria-label={STRINGS.detailTitle}>
      <h1>{STRINGS.detailTitle}</h1>
      <EmergencyBanner />
      {domainId === "" || intentId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <DetailBody key={`${domainId}|${intentId}`} domainId={domainId} intentId={intentId} />
      )}
    </section>
  );
}
