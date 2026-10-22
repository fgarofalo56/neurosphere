import {
  Button,
  Field,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { PageTemplate } from "../../design-system";
import { QueryErrorState, StateBadge, slaText } from "./components";
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
  if (query.isPending) return <p aria-busy="true">{STRINGS.loading}</p>;
  const { items, next_cursor: next } = query.data;
  const H = STRINGS.headers;
  return (
    <>
      {items.length === 0 ? (
        <p data-testid="empty-state">{STRINGS.empty}</p>
      ) : (
        <Table aria-label={STRINGS.title}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{H.kind}</TableHeaderCell>
              <TableHeaderCell>{H.subject}</TableHeaderCell>
              <TableHeaderCell>{H.state}</TableHeaderCell>
              <TableHeaderCell>{H.assignee}</TableHeaderCell>
              <TableHeaderCell>{H.sla}</TableHeaderCell>
              <TableHeaderCell>{H.escalation}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.item_id} data-testid="review-row">
                <TableCell>
                  <Link to={itemHref(domainId, item.item_id)}>{item.kind}</Link>
                </TableCell>
                <TableCell>{item.subject_ref}</TableCell>
                <TableCell>
                  <StateBadge state={item.state} />
                </TableCell>
                <TableCell>{item.assignee_pseudonym ?? STRINGS.unassigned}</TableCell>
                <TableCell data-testid="sla-due">{slaText(item.sla_due_at)}</TableCell>
                <TableCell data-testid="escalation-level">
                  {orUnknown(item.escalation_level)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
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
