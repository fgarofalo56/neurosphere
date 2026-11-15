import { Button, Dropdown, Field, Option, makeStyles, tokens } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type ReactElement } from "react";
import { Link } from "react-router";
import { ForbiddenError, type ApiError } from "../../api/index.js";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageTemplate,
  StatusPill,
} from "../../design-system";
import { ChangeConfirmDialog, type ChangeDiffRow } from "../governed-change";
import { ForbiddenState } from "../workspaces/ForbiddenState";
import { useResolveReviewItem, useReviewQueue } from "./data";
import { edgeHref } from "./paths";
import { STRINGS } from "./strings";
import type { ReviewItemView, ReviewResolution } from "./types";

const S = STRINGS.reviewQueue;
const RESOLUTIONS: readonly ReviewResolution[] = ["kept_curation", "accepted_inference"];
const PAGE_LIMIT = 100;
const QUERY_KEY = "curation-review-queue";

const useStyles = makeStyles({
  stack: { display: "flex", flexDirection: "column", rowGap: tokens.spacingVerticalM },
});

/** Human age of an item. Sorting is the server's (oldest first); this is display only. */
export function ageLabel(createdAt: string, now: number = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - new Date(createdAt).getTime()) / 60_000));
  if (minutes < 60) return S.ageMinutes(minutes);
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? S.ageHours(hours) : S.ageDays(Math.floor(hours / 24));
}

function resolveError(error: ApiError | null): string | null {
  if (error === null) return null;
  if (error instanceof ForbiddenError) return S.forbidden;
  if (error.status === 404) return S.notFound;
  return S.generic;
}

function ResolveControl(props: {
  readonly value: ReviewResolution;
  readonly onChange: (value: ReviewResolution) => void;
}): ReactElement {
  return (
    <Field label={S.resolutionLabel} hint={S.resolutionHint}>
      <Dropdown
        data-testid="resolution"
        value={S.resolutions[props.value]}
        selectedOptions={[props.value]}
        onOptionSelect={(_e, d) =>
          props.onChange((d.optionValue ?? "kept_curation") as ReviewResolution)
        }
      >
        {RESOLUTIONS.map((r) => (
          <Option key={r} value={r}>
            {S.resolutions[r]}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

function Queue({ items }: { readonly items: readonly ReviewItemView[] }): ReactElement {
  const client = useQueryClient();
  const resolve = useResolveReviewItem();
  const [target, setTarget] = useState<ReviewItemView | null>(null);
  const [resolution, setResolution] = useState<ReviewResolution>("kept_curation");
  const [done, setDone] = useState("");
  const triggerRef = useRef<HTMLElement | null>(null);

  const close = (): void => {
    setTarget(null);
    resolve.reset();
  };
  const reload = (): Promise<void> => client.invalidateQueries({ queryKey: [QUERY_KEY] });

  const diff: ChangeDiffRow[] =
    target === null
      ? []
      : [
          { field: S.fieldStatus, before: target.status, after: "resolved" },
          { field: S.fieldOutcome, before: "none", after: resolution },
        ];

  return (
    <>
      <DataTable
        label={S.title}
        rows={items}
        getRowId={(r) => r.id}
        getRowProps={(r) => ({ "data-testid": "review-row", "data-item": r.id })}
        columns={[
          {
            key: "age",
            header: S.table.age,
            render: (r) => (
              <time dateTime={r.created_at} title={r.created_at}>
                {ageLabel(r.created_at)}
              </time>
            ),
          },
          {
            key: "edge",
            header: S.table.edge,
            render: (r) => <Link to={edgeHref(r.edge_id)}>{r.edge_id}</Link>,
          },
          { key: "relation", header: S.table.relation, render: (r) => r.relation_type },
          { key: "domain", header: S.table.domain, render: (r) => r.domain_id },
          {
            key: "reason",
            header: S.table.reason,
            render: (r) => <StatusPill label={S.reasons[r.reason]} tone="warning" />,
          },
          {
            key: "confidence",
            header: S.table.confidence,
            render: (r) => `${r.observed_confidence} / ${r.presented_confidence}`,
          },
          {
            key: "action",
            header: S.table.action,
            render: (r) => (
              <Button
                data-testid="resolve-open"
                onClick={(e) => {
                  triggerRef.current = e.currentTarget;
                  setDone("");
                  setResolution("kept_curation");
                  setTarget(r);
                }}
              >
                {S.resolve}
              </Button>
            ),
          },
        ]}
      />
      {done === "" ? null : (
        <p role="status" data-testid="resolve-done">
          {done}
        </p>
      )}
      <ChangeConfirmDialog
        open={target !== null}
        title={S.resolveTitle}
        target={target?.edge_id ?? ""}
        version={target?.id ?? ""}
        diff={diff}
        submitting={resolve.isPending}
        reasonMode="code"
        controls={<ResolveControl value={resolution} onChange={setResolution} />}
        error={resolveError(resolve.error)}
        triggerRef={triggerRef}
        onSubmit={() => {
          if (target === null) return;
          resolve.mutate(
            { itemId: target.id, resolution },
            {
              onSuccess: () => {
                setDone(S.done);
                close();
                void reload();
              },
              // A 404 means it was resolved elsewhere or left the scope: show the real list.
              onError: () => void reload(),
            },
          );
        }}
        onClose={close}
      />
    </>
  );
}

function Body(): ReactElement {
  const q = useReviewQueue({ limit: PAGE_LIMIT });
  if (q.isError) {
    if (q.error instanceof ForbiddenError) {
      return <ForbiddenState workspace="catalog" correlationId={q.error.correlationId} />;
    }
    return (
      <ErrorState
        title={S.failed}
        message={q.error.correlationId === "" ? undefined : `Reference: ${q.error.correlationId}`}
        onRetry={() => void q.refetch()}
        testId="query-error"
      />
    );
  }
  if (q.data === undefined) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={4} />
      </div>
    );
  }
  if (q.data.items.length === 0) return <EmptyState title={S.empty} testId="empty-state" />;
  return <Queue items={q.data.items} />;
}

export function ReviewQueuePage(): ReactElement {
  const styles = useStyles();
  return (
    <PageTemplate title={S.title} description={S.description}>
      <div className={styles.stack}>
        <Body />
      </div>
    </PageTemplate>
  );
}
