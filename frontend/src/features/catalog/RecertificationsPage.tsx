import {
  Button,
  Dropdown,
  Field,
  Input,
  Option,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  Panel,
  StatusPill,
  Timestamp,
} from "../../design-system";
import { useRecertifications } from "./explorerHooks";
import { EntityLink, QueryProblem } from "./explorerParts";
import { EXPLORER_STRINGS } from "./explorerStrings";
import type { RecertInclude } from "./explorerTypes";

const S = EXPLORER_STRINGS.recertifications;

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    columnGap: tokens.spacingHorizontalM,
  },
});

const INCLUDES: readonly RecertInclude[] = ["both", "due", "overdue"];

function Queue({
  withinDays,
  include,
}: {
  readonly withinDays: number;
  readonly include: RecertInclude;
}): ReactElement {
  const q = useRecertifications({ withinDays, include });
  if (q.isError) {
    return <QueryProblem error={q.error} title={S.failed} onRetry={() => void q.refetch()} />;
  }
  if (q.data === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={4} />
      </div>
    );
  }
  const rows = q.data.pages.flatMap((p) => p.items);
  const scanned = q.data.pages[q.data.pages.length - 1]?.scanned ?? 0;
  if (rows.length === 0 && !q.hasNextPage) {
    return <EmptyState title={S.empty} testId="empty-state" />;
  }
  return (
    <>
      <p data-testid="scanned">{S.scanned(scanned)}</p>
      <DataTable
        label={S.title}
        rows={rows}
        getRowId={(r) => r.owner_id}
        getRowProps={(r) => ({ "data-testid": "recert-row", "data-owner": r.owner_id })}
        columns={[
          { key: "owner", header: S.table.owner, render: (r) => <EntityLink id={r.owner_id} /> },
          { key: "domain", header: S.table.domain, render: (r) => r.domain_id },
          { key: "kind", header: S.table.kind, render: (r) => r.owner_kind },
          {
            key: "recertified",
            header: S.table.recertified,
            render: (r) => <Timestamp value={r.recertified_at} />,
          },
          { key: "by", header: S.table.by, render: (r) => <Timestamp value={r.recertify_by} /> },
          {
            key: "state",
            header: S.table.state,
            render: (r) => (
              <StatusPill
                label={S.state[r.state]}
                tone={r.state === "overdue" ? "danger" : "warning"}
              />
            ),
          },
          { key: "days", header: S.table.days, render: (r) => S.days(r.days_until_due) },
        ]}
      />
      {q.hasNextPage ? (
        <Button
          data-testid="load-more"
          disabled={q.isFetchingNextPage}
          onClick={() => void q.fetchNextPage()}
        >
          {S.loadMore}
        </Button>
      ) : null}
    </>
  );
}

export function RecertificationsPage(): ReactElement {
  const styles = useStyles();
  const [days, setDays] = useState("30");
  const [include, setInclude] = useState<RecertInclude>("both");
  const n = Number(days);
  const valid = Number.isInteger(n) && n >= 0 && n <= 365;
  return (
    <PageTemplate title={S.title} description={S.description}>
      <div className={styles.stack}>
        <Panel compact>
          <div className={styles.row}>
            <Field label={S.withinDays} validationState={valid ? "none" : "error"}>
              <Input
                type="number"
                value={days}
                min={0}
                max={365}
                onChange={(_e, d) => setDays(d.value)}
              />
            </Field>
            <Field label={S.include}>
              <Dropdown
                value={S.includeOptions[include]}
                selectedOptions={[include]}
                onOptionSelect={(_e, d) => setInclude((d.optionValue ?? "both") as RecertInclude)}
              >
                {INCLUDES.map((v) => (
                  <Option key={v} value={v}>
                    {S.includeOptions[v]}
                  </Option>
                ))}
              </Dropdown>
            </Field>
          </div>
        </Panel>
        {valid ? <Queue withinDays={n} include={include} /> : null}
      </div>
    </PageTemplate>
  );
}
