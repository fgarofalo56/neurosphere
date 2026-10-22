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
import { ActionDetail } from "./ActionDetail";
import { EmergencyBanner, QueryErrorState, StateBadge } from "./components";
import { useAction, useActionList } from "./hooks";
import { STRINGS } from "./strings";
import { ACTION_STATES, type ActionState, type ActionView } from "./types";

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
  const styles = useStyles();
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
        <Table aria-label={STRINGS.title}>
          <TableHeader>
            <TableRow>
              <TableHeaderCell>{H.kind}</TableHeaderCell>
              <TableHeaderCell>{H.target}</TableHeaderCell>
              <TableHeaderCell>{H.state}</TableHeaderCell>
              <TableHeaderCell>{H.channel}</TableHeaderCell>
              <TableHeaderCell>{H.created}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((v) => (
              <TableRow key={v.intent.intent_id} data-testid="action-row">
                <TableCell>
                  <Link to={detailHref(domainId, v.intent.intent_id)}>{v.intent.action_kind}</Link>
                  {v.advisory ? " (advisory)" : ""}
                </TableCell>
                <TableCell>{v.intent.target.canonical_id}</TableCell>
                <TableCell>
                  <StateBadge state={v.intent.state} />
                </TableCell>
                <TableCell>{v.intent.channel}</TableCell>
                <TableCell>{v.intent.created_at}</TableCell>
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

export function ActionsPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const styles = useStyles();
  const rawState = params.get("state") ?? "";
  const state: ActionState | "" = isState(rawState) ? rawState : "";
  return (
    <PageTemplate
      title={STRINGS.title}
      toolbarLabel="Action filters"
      toolbar={
        <form
          aria-label="Action filters"
          className={styles.filters}
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const next = new URLSearchParams();
            if (domainId !== "") next.set("domain_id", domainId);
            const v = data.get("state");
            if (typeof v === "string" && v.trim() !== "") next.set("state", v.trim());
            setParams(next);
          }}
        >
          <Field label={STRINGS.stateLabel}>
            <Select name="state" defaultValue={state}>
              <option value="">{STRINGS.allStates}</option>
              {ACTION_STATES.map((s) => (
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
      <EmergencyBanner />
      <p>
        <Link to={proposeHref(domainId)}>{STRINGS.proposeLink}</Link>
      </p>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <ListBody key={`${domainId}|${state}`} domainId={domainId} state={state} />
      )}
    </PageTemplate>
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
        <Button
          onClick={() => {
            void query.refetch().then(() => setOverride(null));
          }}
        >
          {STRINGS.refresh}
        </Button>
      </p>
      <ActionDetail domainId={domainId} view={view} onView={setOverride} />
    </>
  );
}

export function ActionDetailPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const intentId = params.get("intent_id") ?? "";
  return (
    <PageTemplate title={STRINGS.detailTitle}>
      <EmergencyBanner />
      {domainId === "" || intentId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        <DetailBody key={`${domainId}|${intentId}`} domainId={domainId} intentId={intentId} />
      )}
    </PageTemplate>
  );
}
