import { Button, Checkbox, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { DataTable, EmptyState, LoadingState, StatusPill } from "../../../design-system";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { isDecimalAmount } from "./decimal";
import { PRICE_SHEETS_KEY, usePriceSheets, useUploadPriceSheet, type PriceSheetView } from "./hooks";

export const PRICE_STRINGS = {
  heading: "Price sheets",
  loading: "Loading price sheets",
  empty: "No price sheet has been uploaded. Costs without a price show as unknown.",
  newest: "Newest",
  upload: "Upload price sheet",
  headers: {
    id: "Snapshot",
    source: "Source",
    retrieved: "Retrieved",
    effective: "Effective",
    clouds: "Clouds",
    rows: "Rows",
    status: "Version",
  },
  rowsField: "Rows (JSON array)",
  rowsHint:
    "Each row needs service_name, sku_name, unit_of_measure and retail_price as a decimal string, for example \"0.0015\".",
  rowsFile: "Upload rows from a JSON file",
  rowsInvalid: "Rows must be a JSON array of objects whose retail_price is a decimal string.",
  synthetic: "Synthetic data",
  created: "Price sheet version created.",
  existing: "That exact price sheet already exists; nothing changed.",
} as const;

/** Rows are valid when each is an object with string amounts (never JSON numbers). */
export function parseRows(text: string): Record<string, unknown>[] | undefined {
  try {
    const parsed: unknown = JSON.parse(text);
    if (!Array.isArray(parsed) || parsed.length === 0) return undefined;
    for (const row of parsed) {
      if (row === null || typeof row !== "object" || Array.isArray(row)) return undefined;
      const r = row as Record<string, unknown>;
      if (typeof r["retail_price"] !== "string" || !isDecimalAmount(r["retail_price"])) {
        return undefined;
      }
      if (r["unit_price"] !== undefined && r["unit_price"] !== null) {
        if (typeof r["unit_price"] !== "string" || !isDecimalAmount(r["unit_price"])) {
          return undefined;
        }
      }
    }
    return parsed as Record<string, unknown>[];
  } catch {
    return undefined;
  }
}

const DATE = /^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$/;
const SLUG = /^[a-z0-9][a-z0-9._-]{0,63}$/;

function newestId(items: readonly PriceSheetView[]): string | undefined {
  let best: PriceSheetView | undefined;
  for (const s of items) {
    if (
      best === undefined ||
      s.effective_date > best.effective_date ||
      (s.effective_date === best.effective_date && s.retrieval_date > best.retrieval_date)
    ) {
      best = s;
    }
  }
  return best?.snapshot_id;
}

export function PriceSheetsPanel(): ReactElement {
  const query = usePriceSheets();
  const upload = useUploadPriceSheet();
  const queryClient = useQueryClient();
  const [snapshotId, setSnapshotId] = useState("");
  const [source, setSource] = useState("provider_price_sheet");
  const [sourceUrl, setSourceUrl] = useState("");
  const [retrieved, setRetrieved] = useState("");
  const [effective, setEffective] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [commercial, setCommercial] = useState(true);
  const [government, setGovernment] = useState(false);
  const [synthetic, setSynthetic] = useState(false);
  const [notes, setNotes] = useState("");
  const [rowsText, setRowsText] = useState("");

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={PRICE_STRINGS.loading} rows={3} />
      </div>
    );
  }
  const items = query.data.data.items;
  const newest = newestId(items);
  const rows = parseRows(rowsText);
  const clouds = [commercial ? "commercial" : "", government ? "government" : ""].filter(
    (c) => c !== "",
  );
  const valid =
    SLUG.test(snapshotId.trim()) &&
    sourceUrl.trim().startsWith("https://") &&
    DATE.test(retrieved) &&
    DATE.test(effective) &&
    /^[A-Z]{3}$/.test(currency) &&
    clouds.length > 0 &&
    rows !== undefined;

  return (
    <section aria-labelledby="price-sheets-heading">
      <h2 id="price-sheets-heading">{PRICE_STRINGS.heading}</h2>
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={PRICE_STRINGS.empty} />
        </div>
      ) : (
        <DataTable
          label={PRICE_STRINGS.heading}
          rows={items}
          getRowId={(r) => r.snapshot_id}
          getRowProps={() => ({ "data-testid": "price-sheet-row" })}
          columns={[
            { key: "id", header: PRICE_STRINGS.headers.id, render: (r) => <code>{r.snapshot_id}</code> },
            {
              key: "source",
              header: PRICE_STRINGS.headers.source,
              render: (r) => `${r.source}${r.synthetic ? " (synthetic)" : ""}`,
            },
            { key: "ret", header: PRICE_STRINGS.headers.retrieved, render: (r) => r.retrieval_date },
            { key: "eff", header: PRICE_STRINGS.headers.effective, render: (r) => r.effective_date },
            { key: "clouds", header: PRICE_STRINGS.headers.clouds, render: (r) => r.clouds.join(", ") },
            { key: "rows", header: PRICE_STRINGS.headers.rows, render: (r) => r.row_count },
            {
              key: "ver",
              header: PRICE_STRINGS.headers.status,
              render: (r) =>
                r.snapshot_id === newest ? (
                  <StatusPill label={PRICE_STRINGS.newest} tone="success" />
                ) : (
                  "Older"
                ),
            },
          ]}
        />
      )}
      <h3>{PRICE_STRINGS.upload}</h3>
      <form
        style={{ display: "grid", gap: 12, maxWidth: 720 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid || rows === undefined) return;
          upload.mutate(
            {
              schema_version: "1.0.0",
              snapshot_id: snapshotId.trim(),
              source,
              source_url: sourceUrl.trim(),
              retrieval_date: retrieved,
              effective_date: effective,
              currency,
              clouds,
              synthetic,
              notes,
              rows,
            },
            { onSuccess: () => void queryClient.invalidateQueries({ queryKey: [PRICE_SHEETS_KEY] }) },
          );
        }}
      >
        <Field label="Snapshot id" required>
          <Input value={snapshotId} onChange={(_e, d) => setSnapshotId(d.value)} />
        </Field>
        <Field label="Source" required>
          <Select value={source} onChange={(_e, d) => setSource(d.value)}>
            <option value="provider_price_sheet">provider_price_sheet</option>
            <option value="azure_retail_prices">azure_retail_prices</option>
          </Select>
        </Field>
        <Field label="Source URL (https)" required>
          <Input value={sourceUrl} onChange={(_e, d) => setSourceUrl(d.value)} />
        </Field>
        <Field label="Retrieval date (YYYY-MM-DD)" required>
          <Input value={retrieved} onChange={(_e, d) => setRetrieved(d.value)} />
        </Field>
        <Field label="Effective date (YYYY-MM-DD)" required>
          <Input value={effective} onChange={(_e, d) => setEffective(d.value)} />
        </Field>
        <Field label="Currency" required>
          <Input value={currency} onChange={(_e, d) => setCurrency(d.value.toUpperCase())} />
        </Field>
        <fieldset>
          <legend>Cloud applicability</legend>
          <Checkbox
            label="commercial"
            checked={commercial}
            onChange={(_e, d) => setCommercial(d.checked === true)}
          />
          <Checkbox
            label="government"
            checked={government}
            onChange={(_e, d) => setGovernment(d.checked === true)}
          />
        </fieldset>
        <Checkbox
          label={PRICE_STRINGS.synthetic}
          checked={synthetic}
          onChange={(_e, d) => setSynthetic(d.checked === true)}
        />
        <Field label="Notes">
          <Textarea value={notes} onChange={(_e, d) => setNotes(d.value)} />
        </Field>
        <Field
          label={PRICE_STRINGS.rowsField}
          required
          hint={PRICE_STRINGS.rowsHint}
          validationState={rowsText.trim() !== "" && rows === undefined ? "error" : "none"}
          validationMessage={
            rowsText.trim() !== "" && rows === undefined ? PRICE_STRINGS.rowsInvalid : undefined
          }
        >
          <Textarea rows={6} value={rowsText} onChange={(_e, d) => setRowsText(d.value)} />
        </Field>
        <Field label={PRICE_STRINGS.rowsFile}>
          <input
            type="file"
            accept="application/json,.json"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file !== undefined) void file.text().then(setRowsText);
            }}
          />
        </Field>
        <div>
          <Button type="submit" appearance="primary" disabled={!valid || upload.isPending}>
            {PRICE_STRINGS.upload}
          </Button>
        </div>
      </form>
      {upload.isError ? (
        <div role="alert" data-testid="upload-error">
          {changeErrorText(upload.error)}
        </div>
      ) : null}
      {upload.isSuccess ? (
        <div role="status" data-testid="upload-done">
          {upload.data.data.created ? PRICE_STRINGS.created : PRICE_STRINGS.existing}{" "}
          {upload.data.data.coverage.models_priced} model(s) priced,{" "}
          {upload.data.data.coverage.models_incomplete.length} incomplete.
          {upload.data.data.coverage.warnings.length === 0 ? null : (
            <ul>
              {upload.data.data.coverage.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
