import { Button, Checkbox, Field, Input, Select } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { DataTable, EmptyState, LoadingState, StatusPill } from "../../../design-system";
import { QueryErrorState } from "../shared/AdminStates";
import { useAdminGet } from "../shared/transport";
import { ConfirmedChange, diffRows, type PendingChange } from "./ConfirmedChange";
import { notificationPaths } from "./paths";
import { NOTIFICATION_STRINGS as S } from "./strings";
import {
  DELIVERY_STATUSES,
  type ChannelKind,
  type ChannelKindInfo,
  type ChannelView,
  type Items,
  type NotificationChannel,
  type TestSendResult,
} from "./types";

export const QUERY_KEY = "admin-notifications";

const VAULT =
  /^https:\/\/[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.(azure\.net|usgovcloudapi\.net)\/secrets\/[A-Za-z0-9-]{1,127}(\/[0-9a-f]{32})?$/;
const SLUG = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const HOST = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/;
const DOMAIN = /^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$/;
const CUSTOMER = /^[a-z0-9._-]+$/;
const LOCAL_URL =
  /^http:\/\/(127\.0\.0\.1|localhost|[a-z][a-z0-9-]{0,62})(:[0-9]{1,5})?(\/[A-Za-z0-9._~%-]{1,128})*\/?$/;

interface Draft {
  channel_id: string;
  display_name: string;
  kind: ChannelKind;
  cloud: "commercial" | "government";
  customer_id: string;
  domain_id: string;
  allowed_host: string;
  endpoint: string;
  hmac: string;
  local_sink: boolean;
  local_sink_url: string;
  enabled: boolean;
}

function emptyDraft(seed: NotificationChannel | undefined): Draft {
  return {
    channel_id: "",
    display_name: "",
    kind: "webhook",
    cloud: seed?.cloud ?? "commercial",
    customer_id: seed?.customer_id ?? "",
    domain_id: seed?.domain_id ?? "",
    allowed_host: "",
    endpoint: "",
    hmac: "",
    local_sink: false,
    local_sink_url: "",
    enabled: true,
  };
}

function draftOf(c: NotificationChannel): Draft {
  return {
    channel_id: c.channel_id,
    display_name: c.display_name,
    kind: c.kind,
    cloud: c.cloud,
    customer_id: c.customer_id,
    domain_id: c.domain_id,
    allowed_host: c.allowed_host,
    endpoint: c.endpoint_credential?.secret_uri ?? "",
    hmac: c.hmac_credential?.secret_uri ?? "",
    local_sink: c.local_sink,
    local_sink_url: c.local_sink_url ?? "",
    enabled: c.enabled,
  };
}

function bodyOf(d: Draft, base: NotificationChannel | undefined): NotificationChannel {
  const ref = (uri: string): { kind: "key_vault_secret"; secret_uri: string } | null =>
    uri.trim() === "" ? null : { kind: "key_vault_secret", secret_uri: uri.trim() };
  return {
    ...base,
    schema_version: base?.schema_version ?? "1.0.0",
    channel_id: d.channel_id,
    cloud: d.cloud,
    customer_id: d.customer_id,
    domain_id: d.domain_id,
    display_name: d.display_name,
    kind: d.kind,
    allowed_host: d.allowed_host,
    endpoint_credential: d.local_sink ? null : ref(d.endpoint),
    hmac_credential: d.local_sink ? null : ref(d.hmac),
    local_sink: d.local_sink,
    local_sink_url: d.local_sink ? d.local_sink_url.trim() : null,
    enabled: d.enabled,
  };
}

function secretError(uri: string, required: boolean): string | undefined {
  if (uri.trim() === "") return required ? S.secretInvalid : undefined;
  return VAULT.test(uri.trim()) ? undefined : S.secretInvalid;
}

function problemsOf(d: Draft, creating: boolean): Record<string, string> {
  const out: Record<string, string> = {};
  if (creating && !SLUG.test(d.channel_id)) out["channel_id"] = "Lower-case letters, digits, . _ -";
  if (d.display_name.trim() === "") out["display_name"] = "Required";
  if (!DOMAIN.test(d.domain_id)) out["domain_id"] = "A canonical domain id";
  if (!CUSTOMER.test(d.customer_id)) out["customer_id"] = "Required";
  if (!HOST.test(d.allowed_host)) out["allowed_host"] = "A bare lower-case host name";
  if (d.local_sink) {
    if (!LOCAL_URL.test(d.local_sink_url.trim())) out["local_sink_url"] = "A plain-HTTP local URL";
  } else {
    const endpoint = secretError(d.endpoint, true);
    if (endpoint !== undefined) out["endpoint"] = endpoint;
    const hmac = secretError(d.hmac, d.kind === "webhook");
    if (hmac !== undefined) out["hmac"] = hmac;
  }
  return out;
}

function ChannelForm({
  existing,
  kinds,
  seed,
  onReview,
  onCancel,
}: {
  readonly existing: ChannelView | undefined;
  readonly kinds: readonly ChannelKindInfo[];
  readonly seed: NotificationChannel | undefined;
  readonly onReview: (draft: Draft) => void;
  readonly onCancel: () => void;
}): ReactElement {
  const creating = existing === undefined;
  const [d, setD] = useState<Draft>(
    existing === undefined ? emptyDraft(seed) : draftOf(existing.channel),
  );
  const problems = problemsOf(d, creating);
  const [touched, setTouched] = useState(false);
  const err = (k: string): { validationState: "error" | "none"; validationMessage?: string } => {
    const message = problems[k];
    return touched && message !== undefined
      ? { validationState: "error", validationMessage: message }
      : { validationState: "none" };
  };
  const set = (patch: Partial<Draft>): void => setD({ ...d, ...patch });
  return (
    <form
      aria-label={creating ? "New channel" : `Edit channel ${d.channel_id}`}
      data-testid="channel-form"
      style={{ display: "grid", gap: 8, maxWidth: 640 }}
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (Object.keys(problems).length === 0) onReview(d);
      }}
    >
      <Field label="Channel id" required {...err("channel_id")}>
        <Input
          value={d.channel_id}
          disabled={!creating}
          onChange={(_e, v) => set({ channel_id: v.value })}
        />
      </Field>
      <Field label="Display name" required {...err("display_name")}>
        <Input value={d.display_name} onChange={(_e, v) => set({ display_name: v.value })} />
      </Field>
      <Field label="Kind">
        <Select
          value={d.kind}
          disabled={!creating}
          onChange={(_e, v) => set({ kind: v.value as ChannelKind })}
        >
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind} disabled={k.status === "not_built"}>
              {S.kindReason(k.kind, k.status, k.reason)}
            </option>
          ))}
        </Select>
      </Field>
      <ul data-testid="kind-notes">
        {kinds
          .filter((k) => k.status !== "buildable")
          .map((k) => (
            <li key={k.kind}>{S.kindReason(k.kind, k.status, k.reason)}</li>
          ))}
      </ul>
      <Field label="Cloud">
        <Select value={d.cloud} onChange={(_e, v) => set({ cloud: v.value as Draft["cloud"] })}>
          <option value="commercial">commercial</option>
          <option value="government">government</option>
        </Select>
      </Field>
      <Field label="Customer id" required {...err("customer_id")}>
        <Input value={d.customer_id} onChange={(_e, v) => set({ customer_id: v.value })} />
      </Field>
      <Field label="Domain id" required {...err("domain_id")}>
        <Input value={d.domain_id} onChange={(_e, v) => set({ domain_id: v.value })} />
      </Field>
      <Field label="Allowed host" required {...err("allowed_host")}>
        <Input value={d.allowed_host} onChange={(_e, v) => set({ allowed_host: v.value })} />
      </Field>
      <p data-testid="secret-note">{S.secretNote}</p>
      <Checkbox
        label="Local sink (development only; refused outside NS_ENV=local)"
        checked={d.local_sink}
        onChange={(_e, v) => set({ local_sink: v.checked === true })}
      />
      {d.local_sink ? (
        <Field label="Local sink URL" required {...err("local_sink_url")}>
          <Input value={d.local_sink_url} onChange={(_e, v) => set({ local_sink_url: v.value })} />
        </Field>
      ) : (
        <>
          <Field label={S.secretLabel("Endpoint secret")} required {...err("endpoint")}>
            <Input value={d.endpoint} onChange={(_e, v) => set({ endpoint: v.value })} />
          </Field>
          <Field
            label={S.secretLabel("Signing secret")}
            required={d.kind === "webhook"}
            {...err("hmac")}
          >
            <Input value={d.hmac} onChange={(_e, v) => set({ hmac: v.value })} />
          </Field>
        </>
      )}
      <Checkbox
        label="Enabled"
        checked={d.enabled}
        onChange={(_e, v) => set({ enabled: v.checked === true })}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <Button type="submit" appearance="primary">
          {S.review}
        </Button>
        <Button type="button" onClick={onCancel}>
          {S.cancelEdit}
        </Button>
      </div>
    </form>
  );
}

function Counts({ view }: { readonly view: ChannelView }): ReactElement {
  const shown = DELIVERY_STATUSES.filter((s) => view.delivery_counts[s] > 0);
  return (
    <span data-testid="channel-counts">
      {shown.length === 0 ? "none" : shown.map((s) => `${s} ${view.delivery_counts[s]}`).join(", ")}
    </span>
  );
}

export function ChannelsPanel(): ReactElement {
  const queryClient = useQueryClient();
  const channels = useAdminGet<Items<ChannelView>>(QUERY_KEY, {
    path: notificationPaths.channels(),
  });
  const kinds = useAdminGet<Items<ChannelKindInfo>>(QUERY_KEY, { path: notificationPaths.kinds() });
  const [form, setForm] = useState<{ existing: ChannelView | undefined } | null>(null);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [onDone, setOnDone] = useState<((data: unknown) => void) | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  if (channels.isError) {
    return <QueryErrorState error={channels.error} onRetry={() => void channels.refetch()} />;
  }
  if (channels.isPending || kinds.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={3} />
      </div>
    );
  }
  if (kinds.isError) {
    return <QueryErrorState error={kinds.error} onRetry={() => void kinds.refetch()} />;
  }
  const rows = channels.data.data.items;

  const ask = (change: PendingChange, after?: (data: unknown) => void): void => {
    setPending(change);
    setOnDone(() => after ?? null);
  };
  const refresh = (): void => void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });

  const review = (d: Draft, existing: ChannelView | undefined): void => {
    const body = bodyOf(d, existing?.channel);
    const diff = diffRows(
      existing === undefined ? null : (existing.channel as unknown as Record<string, unknown>),
      body as unknown as Record<string, unknown>,
    );
    ask(
      existing === undefined
        ? {
            title: "Create channel",
            target: body.channel_id,
            version: "new channel",
            diff,
            request: { method: "POST", path: notificationPaths.channels(), body },
          }
        : {
            title: "Update channel",
            target: body.channel_id,
            version: existing.etag,
            diff,
            request: {
              method: "PUT",
              path: notificationPaths.channel(body.channel_id),
              body,
              ifMatch: existing.etag,
            },
          },
      () => setForm(null),
    );
  };

  const toggle = (view: ChannelView): void => {
    const body = { ...view.channel, enabled: !view.channel.enabled };
    ask({
      title: body.enabled ? "Enable channel" : "Disable channel",
      target: body.channel_id,
      version: view.etag,
      diff: diffRows(
        view.channel as unknown as Record<string, unknown>,
        body as unknown as Record<string, unknown>,
      ),
      request: {
        method: "PUT",
        path: notificationPaths.channel(body.channel_id),
        body,
        ifMatch: view.etag,
      },
    });
  };

  const remove = (view: ChannelView): void =>
    ask({
      title: "Delete channel",
      target: view.channel.channel_id,
      version: view.etag,
      diff: [{ field: "channel", before: view.channel.display_name, after: "deleted" }],
      request: {
        method: "DELETE",
        path: notificationPaths.channel(view.channel.channel_id),
        ifMatch: view.etag,
      },
    });

  const test = (view: ChannelView): void => {
    const id = view.channel.channel_id;
    ask(
      {
        title: "Send test message",
        target: id,
        version: view.etag,
        diff: [{ field: "action", before: "none", after: "send one fixed test message" }],
        request: { method: "POST", path: notificationPaths.channelTest(id) },
      },
      (data) => {
        const r = data as TestSendResult;
        setTestResult(
          r.ok ? S.testOk(id, r.status_code) : S.testFailed(id, r.reason_code, r.status_code),
        );
      },
    );
  };

  return (
    <>
      {testResult === null ? null : (
        <div role="status" data-testid="test-result">
          {testResult}
        </div>
      )}
      {form === null ? (
        <div>
          <Button appearance="primary" onClick={() => setForm({ existing: undefined })}>
            New channel
          </Button>
        </div>
      ) : (
        <ChannelForm
          key={form.existing?.channel.channel_id ?? "new"}
          existing={form.existing}
          kinds={kinds.data.data.items}
          seed={rows[0]?.channel}
          onReview={(d) => review(d, form.existing)}
          onCancel={() => setForm(null)}
        />
      )}
      {rows.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty.channels} />
        </div>
      ) : (
        <DataTable
          label="Channels"
          rows={[...rows]}
          getRowId={(r) => r.channel.channel_id}
          getRowProps={() => ({ "data-testid": "channel-row" })}
          columns={[
            {
              key: "name",
              header: "Channel",
              render: (r) => (
                <>
                  {r.channel.display_name} <code>{r.channel.channel_id}</code>
                </>
              ),
            },
            { key: "kind", header: "Kind", render: (r) => r.channel.kind },
            {
              key: "host",
              header: "Host",
              render: (r) => (
                <code>{r.channel.local_sink ? "local sink" : r.channel.allowed_host}</code>
              ),
            },
            {
              key: "enabled",
              header: "State",
              render: (r) => (
                <StatusPill
                  label={r.channel.enabled ? "Enabled" : "Disabled"}
                  tone={r.channel.enabled ? "success" : "neutral"}
                />
              ),
            },
            { key: "counts", header: "Deliveries", render: (r) => <Counts view={r} /> },
            {
              key: "error",
              header: "Last error",
              render: (r) =>
                r.last_error_code === null ? "none" : <code>{r.last_error_code}</code>,
            },
            {
              key: "actions",
              header: "Actions",
              render: (r) => {
                const id = r.channel.channel_id;
                return (
                  <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
                    <Button
                      size="small"
                      aria-label={`Edit ${id}`}
                      onClick={() => setForm({ existing: r })}
                    >
                      Edit
                    </Button>
                    <Button
                      size="small"
                      aria-label={`${r.channel.enabled ? "Disable" : "Enable"} ${id}`}
                      onClick={() => toggle(r)}
                    >
                      {r.channel.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button size="small" aria-label={`Send test to ${id}`} onClick={() => test(r)}>
                      Send test
                    </Button>
                    <Button size="small" aria-label={`Delete ${id}`} onClick={() => remove(r)}>
                      Delete
                    </Button>
                  </span>
                );
              },
            },
          ]}
        />
      )}
      {pending === null ? null : (
        <ConfirmedChange
          change={pending}
          onClose={() => setPending(null)}
          onDone={(response) => {
            setPending(null);
            onDone?.(response.data);
            refresh();
          }}
        />
      )}
    </>
  );
}
