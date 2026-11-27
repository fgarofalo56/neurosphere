import { Field, Select } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import {
  DataTable,
  EmptyState,
  LoadingState,
  StatusPill,
  type StatusTone,
} from "../../../design-system";
import { QueryErrorState } from "../shared/AdminStates";
import { useAdminGet } from "../shared/transport";
import { QUERY_KEY } from "./ChannelsPanel";
import { notificationPaths } from "./paths";
import { NOTIFICATION_STRINGS as S } from "./strings";
import {
  DELIVERY_STATUSES,
  type ChannelView,
  type DeliveryStatus,
  type Items,
  type NotificationDelivery,
} from "./types";

const TONE: Record<DeliveryStatus, StatusTone> = {
  pending: "info",
  sending: "info",
  delivered: "success",
  failed: "danger",
  dead_lettered: "danger",
  suppressed: "neutral",
};

export function DeliveriesPanel(): ReactElement {
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const channels = useAdminGet<Items<ChannelView>>(QUERY_KEY, {
    path: notificationPaths.channels(),
  });
  const query = useAdminGet<Items<NotificationDelivery>>(QUERY_KEY, {
    path: notificationPaths.deliveries(),
    query: {
      status: status === "" ? undefined : status,
      channel_id: channel === "" ? undefined : channel,
      limit: 100,
    },
  });
  const filters = (
    <div style={{ display: "flex", gap: 8 }}>
      <Field label="Status filter">
        <Select value={status} onChange={(_e, v) => setStatus(v.value)}>
          <option value="">All statuses</option>
          {DELIVERY_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Channel filter">
        <Select value={channel} onChange={(_e, v) => setChannel(v.value)}>
          <option value="">All channels</option>
          {(channels.data?.data.items ?? []).map((c) => (
            <option key={c.channel.channel_id} value={c.channel.channel_id}>
              {c.channel.channel_id}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
  if (query.isError) {
    return <QueryErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending) {
    return (
      <>
        {filters}
        <div aria-busy="true" data-testid="loading-state">
          <LoadingState label={S.loading} rows={3} />
        </div>
      </>
    );
  }
  const rows = query.data.data.items;
  return (
    <>
      {filters}
      {rows.length === 0 ? (
        <div data-testid="empty-state">
          <EmptyState title={S.empty.deliveries} />
        </div>
      ) : (
        <DataTable
          label="Deliveries"
          rows={[...rows]}
          getRowId={(r) => r.notification_id}
          getRowProps={() => ({ "data-testid": "delivery-row" })}
          columns={[
            {
              key: "status",
              header: "Status",
              render: (r) => <StatusPill label={r.status} tone={TONE[r.status]} />,
            },
            { key: "event", header: "Event class", render: (r) => r.event_class },
            { key: "channel", header: "Channel", render: (r) => <code>{r.channel_id}</code> },
            { key: "attempts", header: "Attempts", render: (r) => r.attempts },
            {
              key: "error",
              header: "Last error",
              render: (r) =>
                r.last_error_code === null || r.last_error_code === undefined ? (
                  "none"
                ) : (
                  <code>{r.last_error_code}</code>
                ),
            },
            { key: "created", header: "Created", render: (r) => r.created_at },
            { key: "delivered", header: "Delivered", render: (r) => r.delivered_at ?? "not yet" },
          ]}
        />
      )}
    </>
  );
}
