import { Button, Field, Select, makeStyles, tokens } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
import { useSelectedDomain } from "../../app/domain";
import { PageTemplate } from "../../design-system";
import { PublicationBadge, QueryErrorState } from "./components";
import { useReportList } from "./hooks";
import { reportViewHref } from "./paths";
import { STRINGS } from "./strings";

const PAGE_SIZE = 25;

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
              <th scope="col">{STRINGS.headers.title}</th>
              <th scope="col">{STRINGS.headers.publication}</th>
              <th scope="col">{STRINGS.headers.updated}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((report) => (
              <tr key={report.id} data-testid="report-row">
                <td>
                  <Link to={reportViewHref(report.domain_id, report.id)}>{report.title}</Link>
                  {report.is_owner ? ` (${STRINGS.youAreOwner})` : ""}
                </td>
                <td>
                  <PublicationBadge state={report.publication.state} />
                </td>
                <td>{report.updated_at}</td>
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
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        // Re-keyed so a new filter resets the cursor history.
        <ListBody key={`${domainId}|${pending}`} domainId={domainId} pending={pending} />
      )}
    </PageTemplate>
  );
}
