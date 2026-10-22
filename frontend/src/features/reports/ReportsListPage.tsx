import { useId, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router";
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

export function ReportsListPage(): ReactElement {
  const [params, setParams] = useSearchParams();
  const domainId = params.get("domain_id") ?? "";
  const pending = params.get("publication") === "pending";
  const ids = { domain: useId(), filter: useId() };

  return (
    <section aria-label={STRINGS.listTitle}>
      <h1>{STRINGS.listTitle}</h1>
      <form
        aria-label="Report filters"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          const domain = data.get("domain_id");
          const filter = data.get("publication");
          const next = new URLSearchParams();
          if (typeof domain === "string" && domain.trim() !== "") {
            next.set("domain_id", domain.trim());
          }
          if (filter === "pending") next.set("publication", "pending");
          setParams(next);
        }}
      >
        <label htmlFor={ids.domain}>{STRINGS.domainLabel}</label>{" "}
        <input id={ids.domain} name="domain_id" defaultValue={domainId} />{" "}
        <label htmlFor={ids.filter}>{STRINGS.filterLabel}</label>{" "}
        <select id={ids.filter} name="publication" defaultValue={pending ? "pending" : ""}>
          <option value="">{STRINGS.allReports}</option>
          <option value="pending">{STRINGS.pendingFilter}</option>
        </select>{" "}
        <button type="submit">{STRINGS.apply}</button>
      </form>
      {domainId === "" ? (
        <p data-testid="domain-required">{STRINGS.domainRequired}</p>
      ) : (
        // Re-keyed so a new filter resets the cursor history.
        <ListBody key={`${domainId}|${pending}`} domainId={domainId} pending={pending} />
      )}
    </section>
  );
}
