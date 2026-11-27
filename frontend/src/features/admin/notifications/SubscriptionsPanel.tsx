import { Button, Checkbox, Field, Input, Select } from "@fluentui/react-components";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";
import { DataTable, EmptyState, LoadingState, StatusPill } from "../../../design-system";
import { QueryErrorState } from "../shared/AdminStates";
import { useAdminGet } from "../shared/transport";
import { QUERY_KEY } from "./ChannelsPanel";
import { ConfirmedChange, diffRows, type PendingChange } from "./ConfirmedChange";
import { notificationPaths } from "./paths";
import { NOTIFICATION_STRINGS as S } from "./strings";
import {
  AUDIENCE_ROLES,
  EVENT_CLASSES,
  SEVERITIES,
  type AudienceRole,
  type ChannelView,
  type EventClass,
  type Items,
  type NotificationSubscription,
  type Severity,
  type SubscriptionView,
} from "./types";

const SLUG = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const DOMAIN = /^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+$/;
const CUSTOMER = /^[a-z0-9._-]+$/;

function blank(seed: ChannelView | undefined): NotificationSubscription {
  return {
    schema_version: "1.0.0",
    subscription_id: "",
    cloud: seed?.channel.cloud ?? "commercial",
    customer_id: seed?.channel.customer_id ?? "",
    domain_id: seed?.channel.domain_id ?? "",
    channel_id: seed?.channel.channel_id ?? "",
    event_classes: [],
    audience_roles: [],
    min_severity: "medium",
    enabled: true,
  };
}

function toggled<T extends string>(list: readonly T[], value: T, on: boolean): T[] {
  const without = list.filter((x) => x !== value);
  return on ? [...without, value] : without;
}

function SubscriptionForm({
  existing,
  channels,
  seed,
  onReview,
  onCancel,
}: {
  readonly existing: SubscriptionView | undefined;
  readonly channels: readonly ChannelView[];
  readonly seed: ChannelView | undefined;
  readonly onReview: (s: NotificationSubscription) => void;
  readonly onCancel: () => void;
}): ReactElement {
  const creating = existing === undefined;
  const [s, setS] = useState<NotificationSubscription>(existing?.subscription ?? blank(seed));
  const [touched, setTouched] = useState(false);
  const problems: Record<string, string> = {};
  if (creating && !SLUG.test(s.subscription_id))
    problems["id"] = "Lower-case letters, digits, . _ -";
  if (s.channel_id === "") problems["channel"] = "Pick a channel";
  if (!DOMAIN.test(s.domain_id)) problems["domain"] = "A canonical domain id";
  if (!CUSTOMER.test(s.customer_id)) problems["customer"] = "Required";
  if (s.event_classes.length === 0) problems["events"] = "Pick at least one event class";
  if (s.audience_roles.length === 0) problems["roles"] = "Pick at least one role";
  const err = (k: string): { validationState: "error" | "none"; validationMessage?: string } => {
    const message = problems[k];
    return touched && message !== undefined
      ? { validationState: "error", validationMessage: message }
      : { validationState: "none" };
  };
  return (
    <form
      aria-label={creating ? "New subscription" : `Edit subscription ${s.subscription_id}`}
      data-testid="subscription-form"
      style={{ display: "grid", gap: 8, maxWidth: 640 }}
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (Object.keys(problems).length === 0) onReview(s);
      }}
    >
      <Field label="Subscription id" required {...err("id")}>
        <Input
          value={s.subscription_id}
          disabled={!creating}
          onChange={(_e, v) => setS({ ...s, subscription_id: v.value })}
        />
      </Field>
      <Field label="Channel" required {...err("channel")}>
        <Select value={s.channel_id} onChange={(_e, v) => setS({ ...s, channel_id: v.value })}>
          <option value="">Select a channel</option>
          {channels.map((c) => (
            <option key={c.channel.channel_id} value={c.channel.channel_id}>
              {c.channel.display_name} ({c.channel.channel_id})
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Cloud">
        <Select
          value={s.cloud}
          onChange={(_e, v) => setS({ ...s, cloud: v.value as NotificationSubscription["cloud"] })}
        >
          <option value="commercial">commercial</option>
          <option value="government">government</option>
        </Select>
      </Field>
      <Field label="Customer id" required {...err("customer")}>
        <Input value={s.customer_id} onChange={(_e, v) => setS({ ...s, customer_id: v.value })} />
      </Field>
      <Field label="Domain id" required {...err("domain")}>
        <Input value={s.domain_id} onChange={(_e, v) => setS({ ...s, domain_id: v.value })} />
      </Field>
      <fieldset style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
        <legend>Event classes (required)</legend>
        {EVENT_CLASSES.map((c) => (
          <Checkbox
            key={c}
            label={c}
            checked={s.event_classes.includes(c)}
            onChange={(_e, v) =>
              setS({
                ...s,
                event_classes: toggled<EventClass>(s.event_classes, c, v.checked === true),
              })
            }
          />
        ))}
      </fieldset>
      {touched && problems["events"] !== undefined ? (
        <span role="alert">{problems["events"]}</span>
      ) : null}
      <fieldset>
        <legend>Audience roles (required)</legend>
        {AUDIENCE_ROLES.map((r) => (
          <Checkbox
            key={r}
            label={r}
            checked={s.audience_roles.includes(r)}
            onChange={(_e, v) =>
              setS({
                ...s,
                audience_roles: toggled<AudienceRole>(s.audience_roles, r, v.checked === true),
              })
            }
          />
        ))}
      </fieldset>
      {touched && problems["roles"] !== undefined ? (
        <span role="alert">{problems["roles"]}</span>
      ) : null}
      <Field label="Minimum severity">
        <Select
          value={s.min_severity}
          onChange={(_e, v) => setS({ ...s, min_severity: v.value as Severity })}
        >
          {SEVERITIES.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </Select>
      </Field>
      <Checkbox
        label="Enabled"
        checked={s.enabled}
        onChange={(_e, v) => setS({ ...s, enabled: v.checked === true })}
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

export function SubscriptionsPanel(): ReactElement {
  const queryClient = useQueryClient();
  const subs = useAdminGet<Items<SubscriptionView>>(QUERY_KEY, {
    path: notificationPaths.subscriptions(),
  });
  const channels = useAdminGet<Items<ChannelView>>(QUERY_KEY, {
    path: notificationPaths.channels(),
  });
  const [form, setForm] = useState<{ existing: SubscriptionView | undefined } | null>(null);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [onDone, setOnDone] = useState<(() => void) | null>(null);

  if (subs.isError) {
    return <QueryErrorState error={subs.error} onRetry={() => void subs.refetch()} />;
  }
  if (subs.isPending || channels.isPending) {
    return (
      <div aria-busy="true" data-testid="loading-state">
        <LoadingState label={S.loading} rows={3} />
      </div>
    );
  }
  if (channels.isError) {
    return <QueryErrorState error={channels.error} onRetry={() => void channels.refetch()} />;
  }
  const rows = subs.data.data.items;
  const channelRows = channels.data.data.items;

  const ask = (change: PendingChange, after?: () => void): void => {
    setPending(change);
    setOnDone(() => after ?? null);
  };

  const review = (s: NotificationSubscription, existing: SubscriptionView | undefined): void => {
    const diff = diffRows(
      existing === undefined ? null : (existing.subscription as unknown as Record<string, unknown>),
      s as unknown as Record<string, unknown>,
    );
    ask(
      existing === undefined
        ? {
            title: "Create subscription",
            target: s.subscription_id,
            version: "new subscription",
            diff,
            request: { method: "POST", path: notificationPaths.subscriptions(), body: s },
          }
        : {
            title: "Update subscription",
            target: s.subscription_id,
            version: existing.etag,
            diff,
            request: {
              method: "PUT",
              path: notificationPaths.subscription(s.subscription_id),
              body: s,
              ifMatch: existing.etag,
            },
          },
      () => setForm(null),
    );
  };

  const toggle = (view: SubscriptionView): void => {
    const body = { ...view.subscription, enabled: !view.subscription.enabled };
    ask({
      title: body.enabled ? "Enable subscription" : "Disable subscription",
      target: body.subscription_id,
      version: view.etag,
      diff: diffRows(
        view.subscription as unknown as Record<string, unknown>,
        body as unknown as Record<string, unknown>,
      ),
      request: {
        method: "PUT",
        path: notificationPaths.subscription(body.subscription_id),
        body,
        ifMatch: view.etag,
      },
    });
  };

  const remove = (view: SubscriptionView): void =>
    ask({
      title: "Delete subscription",
      target: view.subscription.subscription_id,
      version: view.etag,
      diff: [
        {
          field: "subscription",
          before: view.subscription.event_classes.join(", "),
          after: "deleted",
        },
      ],
      request: {
        method: "DELETE",
        path: notificationPaths.subscription(view.subscription.subscription_id),
        ifMatch: view.etag,
      },
    });

  return (
    <>
      {form === null ? (
        <div>
          <Button
            appearance="primary"
            disabled={channelRows.length === 0}
            onClick={() => setForm({ existing: undefined })}
          >
            New subscription
          </Button>
          {channelRows.length === 0 ? <p>Create a channel first.</p> : null}
        </div>
      ) : (
        <SubscriptionForm
          key={form.existing?.subscription.subscription_id ?? "new"}
          existing={form.existing}
          channels={channelRows}
          seed={channelRows[0]}
          onReview={(s) => review(s, form.existing)}
          onCancel={() => setForm(null)}
        />
      )}
      {rows.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty.subscriptions} />
        </div>
      ) : (
        <DataTable
          label="Subscriptions"
          rows={[...rows]}
          getRowId={(r) => r.subscription.subscription_id}
          getRowProps={() => ({ "data-testid": "subscription-row" })}
          columns={[
            {
              key: "id",
              header: "Subscription",
              render: (r) => <code>{r.subscription.subscription_id}</code>,
            },
            {
              key: "channel",
              header: "Channel",
              render: (r) => <code>{r.subscription.channel_id}</code>,
            },
            {
              key: "domain",
              header: "Domain",
              render: (r) => <code>{r.subscription.domain_id}</code>,
            },
            {
              key: "events",
              header: "Event classes",
              render: (r) => r.subscription.event_classes.join(", "),
            },
            {
              key: "roles",
              header: "Audience roles",
              render: (r) => r.subscription.audience_roles.join(", "),
            },
            { key: "severity", header: "Min severity", render: (r) => r.subscription.min_severity },
            {
              key: "enabled",
              header: "State",
              render: (r) => (
                <StatusPill
                  label={r.subscription.enabled ? "Enabled" : "Disabled"}
                  tone={r.subscription.enabled ? "success" : "neutral"}
                />
              ),
            },
            {
              key: "actions",
              header: "Actions",
              render: (r) => {
                const id = r.subscription.subscription_id;
                return (
                  <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
                    <Button
                      size="small"
                      aria-label={`Edit subscription ${id}`}
                      onClick={() => setForm({ existing: r })}
                    >
                      Edit
                    </Button>
                    <Button
                      size="small"
                      aria-label={`${r.subscription.enabled ? "Disable" : "Enable"} subscription ${id}`}
                      onClick={() => toggle(r)}
                    >
                      {r.subscription.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      size="small"
                      aria-label={`Delete subscription ${id}`}
                      onClick={() => remove(r)}
                    >
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
          onDone={() => {
            setPending(null);
            onDone?.();
            void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
          }}
        />
      )}
    </>
  );
}
