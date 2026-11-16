import { Button, Checkbox, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  PageTemplate,
  StatusPill,
} from "../../../design-system";
import { ChangeConfirmDialog } from "../../governed-change";
import { QueryErrorState, changeErrorText } from "../shared/AdminStates";
import { AdminTabs } from "../shared/AdminTabs";
import { CredentialReferenceField } from "./CredentialReferenceField";
import {
  EMPTY_CREDENTIAL,
  credentialProblem,
  describeReference,
  fromReference,
  toReference,
  type CredentialDraft,
} from "./credentialReference";
import {
  CONNECTORS_KEY,
  useConnectorAction,
  useConnectors,
  useCreateConnector,
  useInvalidate,
  useReadConnector,
  useReadableDomains,
  useReplaceConnector,
  type ConnectorAction,
} from "./hooks";
import { CONNECTOR_STRINGS as S } from "./strings";
import {
  CONNECTOR_KINDS,
  type ConnectorConfigBody,
  type ConnectorKind,
  type ConnectorView,
  type SettingScalar,
} from "./types";

const SLUG = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SETTING_NAME = /^[a-z][a-z0-9_]{0,63}$/;

/** Parses name=value lines into bounded scalars, or undefined when a line is malformed. */
export function parseSettings(text: string): Record<string, SettingScalar> | undefined {
  const out: Record<string, SettingScalar> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line === "") continue;
    const at = line.indexOf("=");
    if (at < 1) return undefined;
    const name = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    if (!SETTING_NAME.test(name) || value.length > 512) return undefined;
    if (value === "true") out[name] = true;
    else if (value === "false") out[name] = false;
    else if (/^-?\d{1,15}$/.test(value)) out[name] = Number(value);
    else out[name] = value;
  }
  return out;
}

export function settingsToText(settings: Readonly<Record<string, SettingScalar>>): string {
  return Object.entries(settings)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join("\n");
}

interface Form {
  readonly connectorId: string;
  readonly kind: ConnectorKind;
  readonly domainIds: readonly string[];
  readonly settingsText: string;
  readonly credential: CredentialDraft;
  readonly enabled: boolean;
}

const EMPTY_FORM: Form = {
  connectorId: "",
  kind: "gateway_poll",
  domainIds: [],
  settingsText: "",
  credential: EMPTY_CREDENTIAL,
  enabled: true,
};

type Dialogs =
  | { readonly kind: "create" }
  | { readonly kind: "replace"; readonly view: ConnectorView; readonly etag: string | undefined }
  | {
      readonly kind: "action";
      readonly view: ConnectorView;
      readonly action: ConnectorAction;
      readonly etag: string | undefined;
    };

function ConnectorsBody(): ReactElement {
  const [kindFilter, setKindFilter] = useState("");
  const query = useConnectors(kindFilter === "" ? undefined : kindFilter);
  const domains = useReadableDomains();
  const create = useCreateConnector();
  const replace = useReplaceConnector();
  const act = useConnectorAction();
  const read = useReadConnector();
  const invalidate = useInvalidate(CONNECTORS_KEY);
  const [dialog, setDialog] = useState<Dialogs | null>(null);
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [done, setDone] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<readonly string[]>([]);

  const closeDialog = (): void => {
    setDialog(null);
    create.reset();
    replace.reset();
    act.reset();
  };
  const finish = (what: string, view?: ConnectorView): void => {
    setDone(S.done(what));
    setWarnings(view?.warnings ?? []);
    setDialog(null);
    void invalidate();
  };
  const openRead = (view: ConnectorView, next: (etag: string | undefined) => Dialogs): void => {
    closeDialog();
    setDone(null);
    read.mutate(view.connector_id, { onSuccess: (r) => setDialog(next(r.etag)) });
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
  const items = query.data.data.items;
  const readable = domains.data?.data.items ?? [];
  const settings = parseSettings(form.settingsText);
  const credentialClear = form.credential.kind === "none" || credentialProblem(form.credential) === undefined;
  const formValid =
    SLUG.test(form.connectorId.trim()) &&
    form.domainIds.length > 0 &&
    settings !== undefined &&
    credentialClear;

  const body = (): ConnectorConfigBody | undefined =>
    settings === undefined
      ? undefined
      : {
          schema_version: "1.0.0",
          connector_id: form.connectorId.trim(),
          connector_kind: form.kind,
          domain_ids: form.domainIds,
          settings,
          credential: toReference(form.credential),
          enabled: form.enabled,
        };

  const controls = (idLocked: boolean): ReactElement => (
    <>
      <Field label={S.fields.id} required>
        <Input
          disabled={idLocked}
          value={form.connectorId}
          onChange={(_e, d) => setForm({ ...form, connectorId: d.value })}
        />
      </Field>
      <Field label={S.fields.kind} required>
        <Select
          disabled={idLocked}
          value={form.kind}
          onChange={(_e, d) => setForm({ ...form, kind: d.value as ConnectorKind })}
        >
          {CONNECTOR_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </Select>
      </Field>
      <fieldset>
        <legend>{S.fields.domains}</legend>
        {readable.map((d) => (
          <Checkbox
            key={d.domain_id}
            label={`${d.display_name} (${d.domain_id})`}
            checked={form.domainIds.includes(d.domain_id)}
            onChange={(_e, data) =>
              setForm({
                ...form,
                domainIds:
                  data.checked === true
                    ? [...form.domainIds, d.domain_id]
                    : form.domainIds.filter((x) => x !== d.domain_id),
              })
            }
          />
        ))}
      </fieldset>
      <Field
        label={S.fields.settings}
        hint={S.settingsHint}
        validationState={settings === undefined ? "error" : "none"}
        validationMessage={settings === undefined ? S.settingsInvalid : undefined}
      >
        <Textarea
          value={form.settingsText}
          onChange={(_e, d) => setForm({ ...form, settingsText: d.value })}
        />
      </Field>
      <CredentialReferenceField
        value={form.credential}
        onChange={(credential) => setForm({ ...form, credential })}
      />
      <Checkbox
        label={S.fields.enabled}
        checked={form.enabled}
        onChange={(_e, d) => setForm({ ...form, enabled: d.checked === true })}
      />
    </>
  );

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "end" }}>
        <Button
          appearance="primary"
          onClick={() => {
            closeDialog();
            setDone(null);
            setForm(EMPTY_FORM);
            setDialog({ kind: "create" });
          }}
        >
          {S.create}
        </Button>
        <Field label="Filter by kind">
          <Select value={kindFilter} onChange={(_e, d) => setKindFilter(d.value)}>
            <option value="">All kinds</option>
            {CONNECTOR_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <p data-testid="restart-note">{S.restartNote}</p>
      {done === null ? null : (
        <div role="status" data-testid="change-done">
          {done}
          {warnings.length === 0 ? null : (
            <ul data-testid="connector-warnings">
              {warnings.map((w) => (
                <li key={w}>{S.warningText(w)}</li>
              ))}
            </ul>
          )}
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
          getRowId={(row) => row.connector_id}
          getRowProps={() => ({ "data-testid": "connector-row" })}
          columns={[
            { key: "id", header: S.headers.id, render: (r) => <code>{r.connector_id}</code> },
            { key: "kind", header: S.headers.kind, render: (r) => r.connector_kind },
            { key: "domains", header: S.headers.domains, render: (r) => r.domain_ids.join(", ") },
            {
              key: "credential",
              header: S.headers.credential,
              render: (r) => describeReference(r.credential),
            },
            {
              key: "status",
              header: S.headers.status,
              render: (r) => (
                <StatusPill
                  label={r.status}
                  tone={r.status === "retired" ? "neutral" : r.enabled ? "success" : "warning"}
                />
              ),
            },
            {
              key: "warnings",
              header: S.headers.warnings,
              render: (r) => (r.warnings ?? []).join(", ") || "None",
            },
            {
              key: "actions",
              header: S.headers.actions,
              render: (r) => (
                <span style={{ display: "inline-flex", gap: 8 }}>
                  <Button
                    size="small"
                    aria-label={`${S.edit} ${r.connector_id}`}
                    disabled={r.status === "retired"}
                    onClick={() => {
                      setForm({
                        connectorId: r.connector_id,
                        kind: r.connector_kind,
                        domainIds: r.domain_ids,
                        settingsText: settingsToText(r.settings),
                        credential: fromReference(r.credential),
                        enabled: r.enabled,
                      });
                      openRead(r, (etag) => ({ kind: "replace", view: r, etag }));
                    }}
                  >
                    {S.edit}
                  </Button>
                  <Button
                    size="small"
                    aria-label={`${r.enabled ? S.disable : S.enable} ${r.connector_id}`}
                    disabled={r.status === "retired"}
                    onClick={() =>
                      openRead(r, (etag) => ({
                        kind: "action",
                        view: r,
                        action: r.enabled ? "disable" : "enable",
                        etag,
                      }))
                    }
                  >
                    {r.enabled ? S.disable : S.enable}
                  </Button>
                  <Button
                    size="small"
                    aria-label={`${S.retire} ${r.connector_id}`}
                    disabled={r.status === "retired"}
                    onClick={() =>
                      openRead(r, (etag) => ({ kind: "action", view: r, action: "retire", etag }))
                    }
                  >
                    {S.retire}
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
          title={S.dialog.create}
          target={form.connectorId.trim() === "" ? "(new connector)" : form.connectorId.trim()}
          version={S.dialog.noVersion}
          diff={[
            {
              field: "connector",
              before: "none",
              after: `${form.kind}, ${form.domainIds.length} domain(s), credential ${form.credential.kind}`,
            },
          ]}
          reasonMode="code"
          controlsValid={formValid}
          reasonNote={S.restartNote}
          submitting={create.isPending}
          error={create.isError ? changeErrorText(create.error) : undefined}
          controls={controls(false)}
          onSubmit={() => {
            const b = body();
            if (b !== undefined) create.mutate(b, { onSuccess: (r) => finish(S.dialog.create, r.data) });
          }}
          onClose={closeDialog}
        />
      ) : null}

      {dialog?.kind === "replace" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog.replace}
          target={dialog.view.connector_id}
          version={dialog.etag ?? "unknown"}
          diff={[
            {
              field: "domains",
              before: dialog.view.domain_ids.join(", "),
              after: form.domainIds.join(", "),
            },
            {
              field: "credential",
              before: describeReference(dialog.view.credential),
              after: describeReference(toReference(form.credential)),
            },
          ]}
          reasonMode="code"
          controlsValid={formValid}
          reasonNote={S.restartNote}
          submitting={replace.isPending}
          error={replace.isError ? changeErrorText(replace.error) : undefined}
          controls={controls(true)}
          onSubmit={() => {
            const b = body();
            if (b !== undefined) {
              replace.mutate(
                { body: b, etag: dialog.etag },
                { onSuccess: (r) => finish(S.dialog.replace, r.data) },
              );
            }
          }}
          onClose={closeDialog}
        />
      ) : null}

      {dialog?.kind === "action" ? (
        <ChangeConfirmDialog
          open
          title={S.dialog[dialog.action]}
          target={dialog.view.connector_id}
          version={dialog.etag ?? "unknown"}
          diff={[
            {
              field: "status",
              before: dialog.view.status,
              after: dialog.action === "retire" ? "retired" : dialog.action === "enable" ? "enabled" : "disabled",
            },
          ]}
          reasonMode="code"
          submitting={act.isPending}
          error={act.isError ? changeErrorText(act.error) : undefined}
          onSubmit={() =>
            act.mutate(
              { connectorId: dialog.view.connector_id, action: dialog.action, etag: dialog.etag },
              { onSuccess: (r) => finish(S.dialog[dialog.action], r.data) },
            )
          }
          onClose={closeDialog}
        />
      ) : null}
    </>
  );
}

export function ConnectorsPage(): ReactElement {
  return (
    <PageTemplate title={S.title} description={S.description}>
      <AdminTabs />
      <ConnectorsBody />
    </PageTemplate>
  );
}
