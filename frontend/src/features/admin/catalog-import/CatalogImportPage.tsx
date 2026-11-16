import { Button, Field, Textarea } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { DataTable, PageTemplate, StatusPill, type StatusTone } from "../../../design-system";
import { changeErrorText } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import { useEtagMutation } from "../shared/transport";
import { existingPaths } from "../sources/apiPaths";
import { MAX_IMPORT_ITEMS, MAX_PREVIEW_ROWS, parsePayload } from "./importPayload";

export const IMPORT_STRINGS = {
  title: "Catalog import",
  description: `Import up to ${MAX_IMPORT_ITEMS} catalog entities as JSON. A dry run is required first; the commit is enabled only for the exact payload that passed it.`,
  field: "Entity documents (JSON)",
  upload: "Upload a JSON file",
  dryRun: "Dry run",
  commit: "Commit import",
  commitDisabled: "Run a clean dry run of this exact payload first.",
  stale: "The payload changed since the dry run. Run it again.",
  clean: "Dry run is clean: every item is valid.",
  notClean: "Dry run found problems. Fix the payload and run it again.",
  committed: "Import committed.",
  notCommitted: "Import did not complete. Items listed as created were written; the rest were not.",
  more: (n: number): string => `${n} more result(s) not shown.`,
  headers: { index: "Item", id: "Id", status: "Result", code: "Code" },
} as const;

interface ImportItemResult {
  readonly index: number;
  readonly id?: string | null;
  readonly status: "valid" | "created" | "rejected" | "failed" | "skipped";
  readonly code?: string | null;
}
interface ImportResult {
  readonly committed: boolean;
  readonly dry_run: boolean;
  readonly items: readonly ImportItemResult[];
}

const TONES: Record<ImportItemResult["status"], StatusTone> = {
  valid: "success",
  created: "success",
  rejected: "danger",
  failed: "danger",
  skipped: "neutral",
};

function Results({ result }: { readonly result: ImportResult }): ReactElement {
  const shown = result.items.slice(0, MAX_PREVIEW_ROWS);
  return (
    <>
      <DataTable
        label="Import results"
        rows={shown}
        getRowId={(row) => String(row.index)}
        getRowProps={() => ({ "data-testid": "import-row" })}
        columns={[
          { key: "index", header: IMPORT_STRINGS.headers.index, render: (r) => r.index + 1 },
          { key: "id", header: IMPORT_STRINGS.headers.id, render: (r) => r.id ?? "" },
          {
            key: "status",
            header: IMPORT_STRINGS.headers.status,
            render: (r) => <StatusPill label={r.status} tone={TONES[r.status]} />,
          },
          { key: "code", header: IMPORT_STRINGS.headers.code, render: (r) => r.code ?? "" },
        ]}
      />
      {result.items.length > shown.length ? (
        <p>{IMPORT_STRINGS.more(result.items.length - shown.length)}</p>
      ) : null}
    </>
  );
}

function ImportBody(): ReactElement {
  const [text, setText] = useState("");
  const [passedDigest, setPassedDigest] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const run = useEtagMutation<
    { readonly items: readonly Record<string, unknown>[]; readonly dryRun: boolean },
    ImportResult
  >((v) => ({
    method: "POST",
    path: existingPaths.catalogImport(),
    body: { items: v.items, dry_run: v.dryRun },
  }));
  const parsed = parsePayload(text);
  const clean = parsed.ok && passedDigest === parsed.digest;
  const showError = text.trim() !== "" && !parsed.ok;

  const go = (dryRun: boolean): void => {
    if (!parsed.ok) return;
    const digest = parsed.digest;
    run.mutate(
      { items: parsed.items, dryRun },
      {
        onSuccess: (r) => {
          setResult(r.data);
          if (dryRun) {
            setPassedDigest(
              r.data.items.length > 0 && r.data.items.every((i) => i.status === "valid")
                ? digest
                : null,
            );
          } else {
            setPassedDigest(null);
          }
        },
      },
    );
  };

  return (
    <>
      <Field
        label={IMPORT_STRINGS.field}
        validationState={showError ? "error" : "none"}
        validationMessage={showError && !parsed.ok ? parsed.error : undefined}
      >
        <Textarea
          rows={10}
          value={text}
          onChange={(_e, d) => {
            setText(d.value);
            setResult(null);
          }}
        />
      </Field>
      <Field label={IMPORT_STRINGS.upload}>
        <input
          type="file"
          accept="application/json,.json"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file === undefined) return;
            void file.text().then((t) => {
              setText(t);
              setResult(null);
            });
          }}
        />
      </Field>
      <div style={{ display: "flex", gap: 12 }}>
        <Button disabled={!parsed.ok || run.isPending} onClick={() => go(true)}>
          {IMPORT_STRINGS.dryRun}
        </Button>
        <Button
          appearance="primary"
          disabled={!clean || run.isPending}
          title={clean ? undefined : IMPORT_STRINGS.commitDisabled}
          onClick={() => go(false)}
        >
          {IMPORT_STRINGS.commit}
        </Button>
      </div>
      {result?.dry_run === true && parsed.ok && passedDigest !== null && !clean ? (
        <p role="status">{IMPORT_STRINGS.stale}</p>
      ) : null}
      {run.isError ? (
        <div role="alert" data-testid="import-error">
          {changeErrorText(run.error)}
        </div>
      ) : null}
      {result === null ? null : (
        <div role="status" data-testid="import-summary">
          {result.dry_run
            ? clean
              ? IMPORT_STRINGS.clean
              : IMPORT_STRINGS.notClean
            : result.committed
              ? IMPORT_STRINGS.committed
              : IMPORT_STRINGS.notCommitted}
        </div>
      )}
      {result === null ? null : <Results result={result} />}
    </>
  );
}

export function CatalogImportPage(): ReactElement {
  return (
    <PageTemplate title={IMPORT_STRINGS.title} description={IMPORT_STRINGS.description}>
      <AdminTabs />
      <ImportBody />
    </PageTemplate>
  );
}
