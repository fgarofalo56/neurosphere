import { Button, Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { EmptyState, LoadingState, PageTemplate, StatusPill } from "../../design-system";
import { RowTable } from "../workspaces/RowTable";
import { QueryErrorState, SlaDue, StateBadge } from "./components";
import { useReviewItems } from "./hooks";
import { STRINGS, orUnknown } from "./strings";
import { REVIEW_KINDS, REVIEW_STATES, type ReviewItemState, type ReviewKind } from "./types";

const PAGE_SIZE = 25;

const useStyles = makeStyles({
  filters: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  pager: {
    display: "flex",
    columnGap: tokens.spacingHorizontalS,
    marginTop: tokens.spacingVerticalS,
  },
});

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
  const styles = useStyles();
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
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={STRINGS.loading} rows={5} />
      </div>
    );
  }
  const { items, next_cursor: next } = query.data;
  const H = STRINGS.headers;
  return (
    <>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={STRINGS.empty} />
        </div>
      ) : (
        <RowTable
          label={STRINGS.title}
          rows={items}
          getRowId={(item) => item.item_id}
          rowTestId="review-row"
          columns={[
            {
              key: "kind",
              header: H.kind,
              render: (item) => <Link to={itemHref(domainId, item.item_id)}>{item.kind}</Link>,
            },
            { key: "subject", header: H.subject, render: (item) => item.subject_ref },
            { key: "state", header: H.state, render: (item) => <StateBadge state={item.state} /> },
            {
              key: "assignee",
              header: H.assignee,
              render: (item) => item.assignee_pseudonym ?? STRINGS.unassigned,
            },
            {
              key: "sla",
              header: H.sla,
              render: (item) => (
                <span data-testid="sla-due">
                  <SlaDue slaDueAt={item.sla_due_at} />
                </span>
              ),
            },
            {
              key: "escalation",
              header: H.escalation,
              render: (item) => (
                <span data-testid="escalation-level">
                  <StatusPill
                    label={orUnknown(item.escalation_level)}
                    tone={item.escalation_level > 0 ? "warning" : "neutral"}
                  />
                </span>
              ),
            },
          ]}
        />
      )}
      <nav aria-label="Pagination" className={styles.pager}>
        <Button disabled={cursors.length <= 1} onClick={() => setCursors((c) => c.slice(0, -1))}>
          {STRINGS.previousPage}
        </Button>
        <Button
          disabled={next === null}
          onClick={() => {
            if (next !== null) setCursors((c) => [...c, next]);
          }}
        >
          {STRINGS.nextPage}
        </Button>
      </nav>
    </>
  );
}

export function ReviewQueuePage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const styles = useStyles();
  const rawKind = params.get("kind") ?? "";
  const rawState = params.get("state") ?? "";
  const kind: ReviewKind | "" = isKind(rawKind) ? rawKind : "";
  const state: ReviewItemState | "" = isState(rawState) ? rawState : "";
  return (
    <PageTemplate
      title={STRINGS.title}
      toolbarLabel="Review filters"
      toolbar={
        <form
          aria-label="Review filters"
          className={styles.filters}
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const next = new URLSearchParams();
            if (domainId !== "") next.set("domain_id", domainId);
            for (const key of ["kind", "state"] as const) {
              const v = data.get(key);
              if (typeof v === "string" && v.trim() !== "") next.set(key, v.trim());
            }
            setParams(next);
          }}
        >
          <Field label={STRINGS.kindLabel}>
            <Select name="kind" defaultValue={kind}>
              <option value="">{STRINGS.allKinds}</option>
              {REVIEW_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={STRINGS.stateLabel}>
            <Select name="state" defaultValue={state}>
              <option value="">{STRINGS.allStates}</option>
              {REVIEW_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit">{STRINGS.apply}</Button>
        </form>
      }
    >
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        <QueueBody
          key={`${domainId}|${kind}|${state}`}
          domainId={domainId}
          kind={kind}
          state={state}
        />
      )}
    </PageTemplate>
  );
}
