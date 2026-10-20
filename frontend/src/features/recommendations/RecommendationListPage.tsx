import { useId, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { AdvisoryBadge, EvidenceStatus, QueryErrorState, ownerText } from "./components";
import { useRecommendations } from "./hooks";
import { KIND_LABELS, STRINGS } from "./strings";
import { RECOMMENDATION_KINDS, type RecommendationKind } from "./types";

const PAGE_SIZE = 25;

function isKind(value: string): value is RecommendationKind {
  return (RECOMMENDATION_KINDS as readonly string[]).includes(value);
}

export function detailHref(domainId: string, recommendationId: string): string {
  const p = new URLSearchParams({ domain_id: domainId, recommendation_id: recommendationId });
  return `/recommendations/detail?${p.toString()}`;
}

function ListBody({
  domainId,
  kind,
  q,
}: {
  readonly domainId: string;
  readonly kind: RecommendationKind | "";
  readonly q: string;
}): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useRecommendations({ domainId, kind, q, cursor, limit: PAGE_SIZE });

  if (query.isError) return <QueryErrorState error={query.error} />;
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const { items, next_cursor: next } = query.data;

  return (
    <>
      {items.length === 0 ? (
        <p data-testid="empty-state">{STRINGS.empty}</p>
      ) : (
        <table aria-label={STRINGS.listTitle}>
          <thead>
            <tr>
              <th scope="col">{STRINGS.kindLabel}</th>
              <th scope="col">{STRINGS.sections.subjects}</th>
              <th scope="col">{STRINGS.sections.owner}</th>
              <th scope="col">Evidence</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((rec) => (
              <tr key={rec.recommendation_id} data-testid="recommendation-row">
                <td>
                  <Link to={detailHref(domainId, rec.recommendation_id)}>
                    {KIND_LABELS[rec.kind]}
                  </Link>
                </td>
                <td>{rec.subject_ids.join(", ")}</td>
                <td>{ownerText(rec.owner)}</td>
                <td>
                  <EvidenceStatus rec={rec} />
                </td>
                <td>
                  <AdvisoryBadge advisory={rec.advisory} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p>
        {cursors.length > 1 ? (
          <button type="button" onClick={() => setCursors([""])}>
            {STRINGS.firstPage}
          </button>
        ) : null}{" "}
        {next !== null ? (
          <button type="button" onClick={() => setCursors([...cursors, next])}>
            {STRINGS.nextPage}
          </button>
        ) : null}
      </p>
    </>
  );
}

export function RecommendationListPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const rawKind = params.get("kind") ?? "";
  const kind: RecommendationKind | "" = isKind(rawKind) ? rawKind : "";
  const q = params.get("q") ?? "";
  const ids = { domain: useId(), kind: useId(), q: useId() };

  return (
    <section aria-label={STRINGS.listTitle}>
      <h1>{STRINGS.listTitle}</h1>
      <form
        aria-label="Recommendation filters"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const text = (key: string): string => {
            const v = data.get(key);
            return typeof v === "string" ? v.trim() : "";
          };
          const next = new URLSearchParams();
          for (const [key, value] of [
            ["domain_id", text("domain_id")],
            ["kind", text("kind")],
            ["q", text("q")],
          ] as const) {
            if (value !== "") next.set(key, value);
          }
          setParams(next);
        }}
      >
        <label htmlFor={ids.domain}>{STRINGS.domainLabel}</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <label htmlFor={ids.kind}>{STRINGS.kindLabel}</label>{" "}
        <select id={ids.kind} name="kind" defaultValue={kind}>
          <option value="">{STRINGS.allKinds}</option>
          {RECOMMENDATION_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>{" "}
        <label htmlFor={ids.q}>{STRINGS.searchLabel}</label>{" "}
        <input id={ids.q} name="q" defaultValue={q} maxLength={200} />{" "}
        <button type="submit">{STRINGS.apply}</button>
      </form>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        // Re-keyed so a new filter resets the cursor history.
        <ListBody key={`${domainId}|${kind}|${q}`} domainId={domainId} kind={kind} q={q} />
      )}
    </section>
  );
}
