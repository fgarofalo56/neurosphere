import { Button, Checkbox, Field, Input, Select } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  StatusPill,
} from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { AdminTabs } from "../shared/AdminTabs";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import {
  useCreateDomain,
  useDomains,
  useInvalidateDomains,
  useReadDomain,
  useRetireDomain,
  type DomainView,
} from "./hooks";
import { CLASSIFICATIONS, DOMAIN_STRINGS as S } from "./strings";

interface CreateForm {
  readonly domainId: string;
  readonly displayName: string;
  readonly classification: string;
  readonly residencyRegion: string;
}

const EMPTY_CREATE: CreateForm = {
  domainId: "",
  displayName: "",
  classification: "internal",
  residencyRegion: "",
};

type Dialog =
  | { readonly kind: "create" }
  | { readonly kind: "retire"; readonly domain: DomainView; readonly etag: string | undefined };

function DomainsBody(): ReactElement {
  const [includeRetired, setIncludeRetired] = useState(false);
  const query = useDomains({ includeRetired });
  const create = useCreateDomain();
  const retire = useRetireDomain();
  const read = useReadDomain();
  const invalidate = useInvalidateDomains();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE);
  const [done, setDone] = useState<string | null>(null);

  const close = (): void => {
    setDialog(null);
    create.reset();
    retire.reset();
  };
  const openCreate = (): void => {
    close();
    setDone(null);
    setForm(EMPTY_CREATE);
    setDialog({ kind: "create" });
  };
  const openRetire = (domain: DomainView): void => {
    close();
    setDone(null);
    // The retire is bound to the domain's current ETag, which only the single read returns.
    read.mutate(domain.domain_id, {
      onSuccess: (result) => setDialog({ kind: "retire", domain, etag: result.etag }),
    });
  };

  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={4} />
      </div>
    );
  }
  const items = query.data.items;
  const createValid =
    form.domainId.trim() !== "" &&
    form.displayName.trim() !== "" &&
    form.residencyRegion.trim() !== "";

  const finish = (what: string): void => {
    setDone(S.done(what));
    setDialog(null);
    void invalidate();
  };

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <Button appearance="primary" onClick={openCreate}>
          {S.create}
        </Button>
        <Checkbox
          label={S.showRetired}
          checked={includeRetired}
          onChange={(_e, data) => setIncludeRetired(data.checked === true)}
        />
      </div>
      {done === null ? null : (
        <div role="status" data-testid="change-done">
          {done}
        </div>
      )}
      {read.isError ? (
        <div role="alert" data-testid="read-error">
          {S.dialog.readFailed} {changeErrorText(read.error)}
        </div>
      ) : null}
      {items.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty} />
        </div>
      ) : (
        <DataTable
          label={S.title}
          rows={items}
          getRowId={(row) => row.domain_id}
          getRowProps={() => ({ "data-testid": "domain-row" })}
          columns={[
            { key: "name", header: S.headers.name, render: (row) => row.display_name },
            { key: "id", header: S.headers.id, render: (row) => <code>{row.domain_id}</code> },
            {
              key: "classification",
              header: S.headers.classification,
              render: (row) => row.classification,
            },
            { key: "region", header: S.headers.region, render: (row) => row.residency_region },
            {
              key: "status",
              header: S.headers.status,
              render: (row) => (
                <StatusPill
                  label={row.status === "active" ? S.active : S.retired}
                  tone={row.status === "active" ? "success" : "neutral"}
                />
              ),
            },
            {
              key: "control",
              header: S.headers.control,
              render: (row) =>
                row.is_control_domain ? (
                  <StatusPill label={S.controlBadge} tone="info" />
                ) : (
                  S.notControl
                ),
            },
            {
              key: "actions",
              header: S.headers.actions,
              render: (row) => (
                <Button
                  size="small"
                  disabled={row.is_control_domain || row.status !== "active"}
                  title={row.is_control_domain ? S.controlCannotRetire : undefined}
                  aria-label={`${S.retire} ${row.display_name}`}
                  onClick={() => openRetire(row)}
                >
                  {S.retire}
                </Button>
              ),
            },
          ]}
        />
      )}

      {dialog?.kind === "create" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog.create}
          target={form.domainId.trim() === "" ? "(new domain)" : form.domainId.trim()}
          version={S.dialog.noVersion}
          diff={[
            {
              field: "domain",
              before: "none",
              after: `${form.displayName.trim() || "?"} (${form.classification}, ${form.residencyRegion.trim() || "?"})`,
            },
          ]}
          reasonMode="code"
          controlsValid={createValid}
          reasonNote={S.dialog.createNote}
          submitting={create.isPending}
          error={create.isError ? changeErrorText(create.error) : undefined}
          controls={
            <>
              <Field label={S.fields.domainId} required>
                <Input
                  value={form.domainId}
                  onChange={(_e, d) => setForm({ ...form, domainId: d.value })}
                />
              </Field>
              <Field label={S.fields.displayName} required>
                <Input
                  value={form.displayName}
                  onChange={(_e, d) => setForm({ ...form, displayName: d.value })}
                />
              </Field>
              <Field label={S.fields.classification} required>
                <Select
                  value={form.classification}
                  onChange={(_e, d) => setForm({ ...form, classification: d.value })}
                >
                  {CLASSIFICATIONS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={S.fields.region} required>
                <Input
                  value={form.residencyRegion}
                  onChange={(_e, d) => setForm({ ...form, residencyRegion: d.value })}
                />
              </Field>
            </>
          }
          onSubmit={() =>
            create.mutate(
              {
                domainId: form.domainId.trim(),
                displayName: form.displayName.trim(),
                classification: form.classification,
                residencyRegion: form.residencyRegion.trim(),
              },
              { onSuccess: () => finish(S.dialog.create) },
            )
          }
          onClose={close}
        />
      ) : null}

      {dialog?.kind === "retire" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog.retire}
          target={dialog.domain.domain_id}
          version={dialog.etag ?? "unknown"}
          diff={[{ field: "status", before: dialog.domain.status, after: "retired" }]}
          reasonMode="code"
          reasonNote={S.dialog.retireNote}
          submitting={retire.isPending}
          error={retire.isError ? changeErrorText(retire.error) : undefined}
          onSubmit={() =>
            retire.mutate(
              { domainId: dialog.domain.domain_id, etag: dialog.etag },
              { onSuccess: () => finish(S.dialog.retire) },
            )
          }
          onClose={close}
        />
      ) : null}
    </>
  );
}

export function DomainsPage(): ReactElement {
  return (
    <PageTemplate title={S.title} description={S.description}>
      <AdminTabs />
      <DomainsBody />
    </PageTemplate>
  );
}
