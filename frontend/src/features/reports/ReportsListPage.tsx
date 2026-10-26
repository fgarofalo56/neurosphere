import { Button, Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { DataTable, EmptyState, LoadingState, PageTemplate, Timestamp } from "../../design-system";
import { PublicationBadge, QueryErrorState } from "./components";
import { useReportList } from "./hooks";
import { reportViewHref } from "./paths";
import { STRINGS } from "./strings";
import type { ReportView } from "./types";

const PAGE_SIZE = 25;

const useStyles = makeStyles({
  form: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  title: { fontWeight: tokens.fontWeightSemibold, overflowWrap: "anywhere" },
});

/** A real table named "Saved reports" (pinned by the a11y specs) with a test id per row. */
function ReportTable({ items }: { readonly items: readonly ReportView[] }): ReactElement {
  const styles = useStyles();
  const H = STRINGS.headers;
  return (
    <DataTable
      label={STRINGS.listTitle}
      rows={items}
      getRowId={(report) => report.id}
      getRowProps={() => ({ "data-testid": "report-row" })}
      columns={[
        {
          key: "title",
          header: H.title,
          render: (report) => (
            <>
              <Link className={styles.title} to={reportViewHref(report.domain_id, report.id)}>
                {report.title}
              </Link>
              {report.is_owner ? <span> ({STRINGS.youAreOwner})</span> : null}
            </>
          ),
        },
        {
          key: "publication",
          header: H.publication,
          render: (report) => <PublicationBadge state={report.publication.state} />,
        },
        {
          key: "updated",
          header: H.updated,
          render: (report) => <Timestamp value={report.updated_at} />,
        },
      ]}
    />
  );
}

function ListBody({
  domainId,
  pending,
}: {
  readonly domainId: string;
  readonly pending: boolean;
}): ReactElement {
  // Cursor history: the last entry is the current page; "" is the first page.
  const [cursors, setCursors] = useState<readonly string[]>([""]);
  const cursor = cursors[cursors.length - 1] ?? "";
  const query = useReportList({
    domainId,
    publicationState: pending ? "pending" : "",
    cursor,
    limit: PAGE_SIZE,
  });

  if (query.isError)
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) {
    return (
      <div aria-busy="true">
        <LoadingState label={STRINGS.loading} />
      </div>
    );
  }
  const { items, next_cursor: next } = query.data;

  return (
    <>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={STRINGS.empty} />
        </div>
      ) : (
        <ReportTable items={items} />
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

function ReportFilters({ pending }: { readonly pending: boolean }): ReactElement {
  const styles = useStyles();
  const [, setParams] = useSearchParams();
  const [filter, setFilter] = useState(pending ? "pending" : "");
  return (
    <form
      aria-label="Report filters"
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        setParams((prev) => {
          const next = new URLSearchParams(prev);
          if (filter === "pending") next.set("publication", "pending");
          else next.delete("publication");
          return next;
        });
      }}
    >
      <Field label={STRINGS.filterLabel}>
        <Select value={filter} onChange={(_e, data) => setFilter(data.value)}>
          <option value="">{STRINGS.allReports}</option>
          <option value="pending">{STRINGS.pendingFilter}</option>
        </Select>
      </Field>
      <Button type="submit" appearance="primary">
        {STRINGS.apply}
      </Button>
    </form>
  );
}

export function ReportsListPage(): ReactElement {
  const [params] = useSearchParams();
  const { domainId } = useSelectedDomain();
  const pending = params.get("publication") === "pending";

  return (
    <PageTemplate
      title={STRINGS.listTitle}
      toolbar={<ReportFilters key={String(pending)} pending={pending} />}
      toolbarLabel="Report filters"
    >
      {domainId === "" ? (
        <div data-testid="domain-required">
          <EmptyState title={STRINGS.domainRequired} />
        </div>
      ) : (
        // Re-keyed so a new filter resets the cursor history.
        <ListBody key={`${domainId}|${pending}`} domainId={domainId} pending={pending} />
      )}
    </PageTemplate>
  );
}
