import { Tab, TabList } from "@fluentui/react-components";
import { useState, type ReactElement } from "react";
import { PageTemplate } from "../../../design-system";
import { AdminTabs } from "../shared/AdminTabs";
import { ChannelsPanel } from "./ChannelsPanel";
import { DeliveriesPanel } from "./DeliveriesPanel";
import { NOTIFICATION_STRINGS as S } from "./strings";
import { SubscriptionsPanel } from "./SubscriptionsPanel";

type TabId = "channels" | "subscriptions" | "deliveries";

/** Notification channels, subscriptions and deliveries (PRP-107 item 7). The API decides access. */
export function NotificationsPage(): ReactElement {
  const [tab, setTab] = useState<TabId>("channels");
  return (
    <PageTemplate title={S.title} description={S.description}>
      <AdminTabs />
      <TabList
        aria-label={S.tabsLabel}
        selectedValue={tab}
        onTabSelect={(_e, data) => setTab(data.value as TabId)}
      >
        <Tab value="channels">{S.tabs.channels}</Tab>
        <Tab value="subscriptions">{S.tabs.subscriptions}</Tab>
        <Tab value="deliveries">{S.tabs.deliveries}</Tab>
      </TabList>
      {tab === "channels" ? <ChannelsPanel /> : null}
      {tab === "subscriptions" ? <SubscriptionsPanel /> : null}
      {tab === "deliveries" ? <DeliveriesPanel /> : null}
    </PageTemplate>
  );
}
