import { Button, Field, Input, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { PageTemplate } from "../../design-system";
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
          <Button onClick={() => setCursors([""])}>{STRINGS.firstPage}</Button>
        ) : null}{" "}
        {next !== null ? (
          <Button onClick={() => setCursors([...cursors, next])}>{STRINGS.nextPage}</Button>
        ) : null}
      </p>
    </>
  );
}

const useStyles = makeStyles({
  form: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
});

function ListFilters({
  kind,
  q,
}: {
  readonly kind: RecommendationKind | "";
  readonly q: string;
}): ReactElement {
  const styles = useStyles();
  const [, setParams] = useSearchParams();
  const [kindValue, setKindValue] = useState<string>(kind);
  const [qValue, setQValue] = useState(q);
  return (
    <form
      aria-label="Recommendation filters"
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        setParams((prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of [
            ["kind", kindValue.trim()],
            ["q", qValue.trim()],
          ] as const) {
            if (value === "") next.delete(key);
            else next.set(key, value);
          }
          return next;
        });
      }}
    >
      <Field label={STRINGS.kindLabel}>
        <Select value={kindValue} onChange={(_e, data) => setKindValue(data.value)}>
          <option value="">{STRINGS.allKinds}</option>
          {RECOMMENDATION_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={STRINGS.searchLabel}>
        <Input value={qValue} maxLength={200} onChange={(_e, data) => setQValue(data.value)} />
      </Field>
      <Button type="submit" appearance="primary">
        {STRINGS.apply}
      </Button>
    </form>
  );
}

export function RecommendationListPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const rawKind = params.get("kind") ?? "";
  const kind: RecommendationKind | "" = isKind(rawKind) ? rawKind : "";
  const q = params.get("q") ?? "";

  return (
    <PageTemplate
      title={STRINGS.listTitle}
      toolbar={<ListFilters key={`${kind}|${q}`} kind={kind} q={q} />}
      toolbarLabel="Recommendation filters"
    >
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        // Re-keyed so a new filter resets the cursor history.
        <ListBody key={`${domainId}|${kind}|${q}`} domainId={domainId} kind={kind} q={q} />
      )}
    </PageTemplate>
  );
}
