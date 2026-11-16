import { Button, Field, Input, Select } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { DataTable, EmptyState, LoadingState } from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { useReadableDomains } from "../sources/hooks";
import { groupAmount, isDecimalAmount, parseThresholds, showAmount } from "./decimal";
import {
  BUDGETS_KEY,
  useBudgets,
  useCreateBudget,
  useReadBudget,
  useReplaceBudget,
  useRetireBudget,
  type BudgetBody,
  type BudgetView,
} from "./hooks";

export const BUDGET_STRINGS = {
  heading: "Budgets",
  loading: "Loading budgets",
  empty: "No budgets are set.",
  create: "Create budget",
  edit: "Edit",
  retire: "Retire",
  headers: {
    id: "Budget",
    domain: "Domain",
    period: "Period",
    amount: "Amount",
    thresholds: "Alert thresholds (%)",
    actions: "Actions",
  },
  dialog: {
    create: "Create budget",
    edit: "Edit budget",
    retire: "Retire budget",
    noVersion: "New budget",
    readFailed: "Could not read the budget before changing it.",
  },
  fields: {
    id: "Budget id",
    domain: "Domain",
    period: "Period",
    amount: "Amount (decimal)",
    currency: "Currency",
    thresholds: "Thresholds in percent, comma separated",
  },
  amountInvalid: "Use a plain decimal such as 1500 or 1500.50.",
  done: (what: string): string => `${what}: done.`,
} as const;

const SLUG = /^[a-z0-9][a-z0-9._-]{0,63}$/;

interface Form {
  readonly budgetId: string;
  readonly domainId: string;
  readonly period: string;
  readonly amount: string;
  readonly currency: string;
  readonly thresholds: string;
}
const EMPTY: Form = {
  budgetId: "",
  domainId: "",
  period: "monthly",
  amount: "",
  currency: "USD",
  thresholds: "50, 80, 100",
};

type Dialogs =
  | { readonly kind: "create" }
  | { readonly kind: "edit"; readonly view: BudgetView; readonly etag: string | undefined }
  | { readonly kind: "retire"; readonly view: BudgetView; readonly etag: string | undefined };

export function BudgetsPanel(): ReactElement {
  const query = useBudgets();
  const domains = useReadableDomains();
  const create = useCreateBudget();
  const replace = useReplaceBudget();
  const retire = useRetireBudget();
  const read = useReadBudget();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialogs | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [done, setDone] = useState<string | null>(null);

  const closeDialog = (): void => {
    setDialog(null);
    create.reset();
    replace.reset();
    retire.reset();
  };
  const finish = (what: string): void => {
    setDone(BUDGET_STRINGS.done(what));
    setDialog(null);
    void queryClient.invalidateQueries({ queryKey: [BUDGETS_KEY] });
  };

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={BUDGET_STRINGS.loading} rows={3} />
      </div>
    );
  }
  const items = query.data.data.items;
  const readable = domains.data?.data.items ?? [];
  const thresholds = parseThresholds(form.thresholds);
  const domainId = form.domainId === "" ? (readable[0]?.domain_id ?? "") : form.domainId;
  const valid =
    SLUG.test(form.budgetId.trim()) &&
    domainId !== "" &&
    isDecimalAmount(form.amount.trim()) &&
    /^[A-Z]{3}$/.test(form.currency) &&
    thresholds !== undefined;
  const body = (): BudgetBody | undefined =>
    thresholds === undefined
      ? undefined
      : {
          schema_version: "1.0.0",
          budget_id: form.budgetId.trim(),
          domain_id: domainId,
          period: form.period,
          amount: form.amount.trim(),
          currency: form.currency,
          thresholds_percent: thresholds,
        };
  const openRead = (view: BudgetView, kind: "edit" | "retire"): void => {
    closeDialog();
    setDone(null);
    read.mutate(view.budget_id, { onSuccess: (r) => setDialog({ kind, view, etag: r.etag }) });
  };

  const controls = (locked: boolean): ReactElement => (
    <>
      <Field label={BUDGET_STRINGS.fields.id} required>
        <Input
          disabled={locked}
          value={form.budgetId}
          onChange={(_e, d) => setForm({ ...form, budgetId: d.value })}
        />
      </Field>
      <Field label={BUDGET_STRINGS.fields.domain} required>
        <Select
          disabled={locked}
          value={domainId}
          onChange={(_e, d) => setForm({ ...form, domainId: d.value })}
        >
          {locked && !readable.some((d) => d.domain_id === domainId) ? (
            <option value={domainId}>{domainId}</option>
          ) : null}
          {readable.map((d) => (
            <option key={d.domain_id} value={d.domain_id}>
              {d.display_name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={BUDGET_STRINGS.fields.period}>
        <Select value={form.period} onChange={(_e, d) => setForm({ ...form, period: d.value })}>
          <option value="monthly">monthly</option>
          <option value="quarterly">quarterly</option>
          <option value="annual">annual</option>
        </Select>
      </Field>
      <Field
        label={BUDGET_STRINGS.fields.amount}
        required
        validationState={form.amount !== "" && !isDecimalAmount(form.amount.trim()) ? "error" : "none"}
        validationMessage={
          form.amount !== "" && !isDecimalAmount(form.amount.trim())
            ? BUDGET_STRINGS.amountInvalid
            : undefined
        }
      >
        <Input value={form.amount} onChange={(_e, d) => setForm({ ...form, amount: d.value })} />
      </Field>
      <Field label={BUDGET_STRINGS.fields.currency} required>
        <Input
          value={form.currency}
          onChange={(_e, d) => setForm({ ...form, currency: d.value.toUpperCase() })}
        />
      </Field>
      <Field
        label={BUDGET_STRINGS.fields.thresholds}
        validationState={thresholds === undefined ? "error" : "none"}
        validationMessage={thresholds === undefined ? "Whole numbers 1 to 1000, at most 10." : undefined}
      >
        <Input
          value={form.thresholds}
          onChange={(_e, d) => setForm({ ...form, thresholds: d.value })}
        />
      </Field>
    </>
  );

  return (
    <section aria-labelledby="budgets-heading">
      <h2 id="budgets-heading">{BUDGET_STRINGS.heading}</h2>
      <Button
        appearance="primary"
        onClick={() => {
          closeDialog();
          setDone(null);
          setForm(EMPTY);
          setDialog({ kind: "create" });
        }}
      >
        {BUDGET_STRINGS.create}
      </Button>
      {done === null ? null : (
        <div role="status" data-testid="change-done">
          {done}
        </div>
      )}
      {read.isError ? (
        <div role="alert" data-testid="read-error">
          {BUDGET_STRINGS.dialog.readFailed} {changeErrorText(read.error)}
        </div>
      ) : null}
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={BUDGET_STRINGS.empty} />
        </div>
      ) : (
        <DataTable
          label={BUDGET_STRINGS.heading}
          rows={items}
          getRowId={(r) => r.budget_id}
          getRowProps={() => ({ "data-testid": "budget-row" })}
          columns={[
            { key: "id", header: BUDGET_STRINGS.headers.id, render: (r) => <code>{r.budget_id}</code> },
            { key: "domain", header: BUDGET_STRINGS.headers.domain, render: (r) => r.domain_id },
            { key: "period", header: BUDGET_STRINGS.headers.period, render: (r) => r.period },
            {
              key: "amount",
              header: BUDGET_STRINGS.headers.amount,
              render: (r) => `${groupAmount(showAmount(r.amount))} ${r.currency}`,
            },
            {
              key: "thr",
              header: BUDGET_STRINGS.headers.thresholds,
              render: (r) => r.thresholds_percent.join(", "),
            },
            {
              key: "actions",
              header: BUDGET_STRINGS.headers.actions,
              render: (r) => (
                <span style={{ display: "inline-flex", gap: 8 }}>
                  <Button
                    size="small"
                    aria-label={`${BUDGET_STRINGS.edit} ${r.budget_id}`}
                    onClick={() => {
                      setForm({
                        budgetId: r.budget_id,
                        domainId: r.domain_id,
                        period: r.period,
                        amount: r.amount,
                        currency: r.currency,
                        thresholds: r.thresholds_percent.join(", "),
                      });
                      openRead(r, "edit");
                    }}
                  >
                    {BUDGET_STRINGS.edit}
                  </Button>
                  <Button
                    size="small"
                    aria-label={`${BUDGET_STRINGS.retire} ${r.budget_id}`}
                    onClick={() => openRead(r, "retire")}
                  >
                    {BUDGET_STRINGS.retire}
                  </Button>
                </span>
              ),
            },
          ]}
        />
      )}

      {dialog?.kind === "create" ? (
        <ChangeConfirmDialog
          open
          title={BUDGET_STRINGS.dialog.create}
          target={form.budgetId.trim() === "" ? "(new budget)" : form.budgetId.trim()}
          version={BUDGET_STRINGS.dialog.noVersion}
          diff={[{ field: "amount", before: "none", after: `${form.amount} ${form.currency} ${form.period}` }]}
          reasonMode="code"
          controlsValid={valid}
          submitting={create.isPending}
          error={create.isError ? changeErrorText(create.error) : undefined}
          controls={controls(false)}
          onSubmit={() => {
            const b = body();
            if (b !== undefined) create.mutate(b, { onSuccess: () => finish(BUDGET_STRINGS.dialog.create) });
          }}
          onClose={closeDialog}
        />
      ) : null}
      {dialog?.kind === "edit" ? (
        <ChangeConfirmDialog
          open
          title={BUDGET_STRINGS.dialog.edit}
          target={dialog.view.budget_id}
          version={dialog.etag ?? "unknown"}
          diff={[
            {
              field: "amount",
              before: `${dialog.view.amount} ${dialog.view.currency} ${dialog.view.period}`,
              after: `${form.amount} ${form.currency} ${form.period}`,
            },
            {
              field: "thresholds",
              before: dialog.view.thresholds_percent.join(", "),
              after: thresholds?.join(", ") ?? "?",
            },
          ]}
          reasonMode="code"
          controlsValid={valid}
          submitting={replace.isPending}
          error={replace.isError ? changeErrorText(replace.error) : undefined}
          controls={controls(true)}
          onSubmit={() => {
            const b = body();
            if (b !== undefined) {
              replace.mutate(
                { body: b, etag: dialog.etag },
                { onSuccess: () => finish(BUDGET_STRINGS.dialog.edit) },
              );
            }
          }}
          onClose={closeDialog}
        />
      ) : null}
      {dialog?.kind === "retire" ? (
        <ChangeConfirmDialog
          open
          title={BUDGET_STRINGS.dialog.retire}
          target={dialog.view.budget_id}
          version={dialog.etag ?? "unknown"}
          diff={[{ field: "status", before: dialog.view.status, after: "retired" }]}
          reasonMode="code"
          submitting={retire.isPending}
          error={retire.isError ? changeErrorText(retire.error) : undefined}
          onSubmit={() =>
            retire.mutate(
              { budgetId: dialog.view.budget_id, etag: dialog.etag },
              { onSuccess: () => finish(BUDGET_STRINGS.dialog.retire) },
            )
          }
          onClose={closeDialog}
        />
      ) : null}
    </section>
  );
}
