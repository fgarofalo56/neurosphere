import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { makeStyles, mergeClasses, tokens, Tab, TabList, Text } from "@fluentui/react-components";
import type { ChartPlan } from "@neurosphere/contracts";
import { ErrorState, Timestamp, useUiStyle } from "../../design-system";
import { ChartTable } from "./ChartTable";
import {
  MSG_ERROR,
  MSG_READY,
  MSG_RENDER,
  MSG_RENDERED,
  PROTOCOL_VERSION,
  parseSandboxMessage,
  specViolations,
  type ParentToSandbox,
} from "./protocol";
import { STRINGS } from "./strings";

export const DEFAULT_SANDBOX_SRC = "/chart-sandbox.html";

/** `rejected`: the plan never left the parent. `failed`: the sandbox could not draw it. */
export type ChartStatus = "loading" | "rendered" | "rejected" | "failed";
export type ChartView = "chart" | "table";

export interface ChartFrameProps {
  /** A plan the server already validated (`validate_chart_plan`); re-checked here defensively. */
  plan: ChartPlan;
  /** Accessible name of the chart and caption of the table view. */
  title?: string;
  initialView?: ChartView;
  /** Height of the chart area in px. */
  height?: number;
  sandboxSrc?: string;
  onStatusChange?: (status: ChartStatus) => void;
}

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    boxSizing: "border-box",
    padding: tokens.spacingHorizontalM,
    backgroundColor: tokens.colorNeutralBackground1,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  lifted: { backgroundColor: tokens.colorNeutralBackground2 },
  raised: { boxShadow: tokens.shadow4 },
  strong: { borderTopColor: tokens.colorNeutralStroke1 },
  radiusSmall: { borderRadius: tokens.borderRadiusSmall },
  radiusMedium: { borderRadius: tokens.borderRadiusMedium },
  frame: { width: "100%", border: "none", backgroundColor: tokens.colorNeutralBackground1 },
  frameFocused: {
    outline: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}`,
    outlineOffset: "2px",
  },
  sources: { color: tokens.colorNeutralForeground3 },
});

export function ChartFrame({
  plan,
  title = STRINGS.frameTitle,
  initialView = "chart",
  height = 320,
  sandboxSrc = DEFAULT_SANDBOX_SRC,
  onStatusChange,
}: ChartFrameProps) {
  const styles = useStyles();
  const { treatment } = useUiStyle();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const counterRef = useRef(0);
  const requestRef = useRef<string | null>(null);
  const [view, setView] = useState<ChartView>(initialView);
  const [status, setStatus] = useState<ChartStatus>("loading");
  const [frameFocused, setFrameFocused] = useState(false);
  const rejected = useMemo(() => specViolations(plan.spec).length > 0, [plan]);

  useEffect(() => {
    onStatusChange?.(rejected ? "rejected" : status);
  }, [rejected, status, onStatusChange]);

  const send = useCallback(() => {
    const target = iframeRef.current?.contentWindow;
    if (rejected || !readyRef.current || !target) return;
    counterRef.current += 1;
    const message: ParentToSandbox = {
      type: MSG_RENDER,
      version: PROTOCOL_VERSION,
      request_id: `r${counterRef.current}`,
      spec: plan.spec,
    };
    requestRef.current = message.request_id;
    setStatus("loading");
    // An opaque-origin target can only be addressed with "*"; the sandbox accepts messages
    // solely from its parent window and the payload is already-governed chart data.
    target.postMessage(message, "*");
  }, [plan, rejected]);

  useEffect(() => {
    if (rejected) return undefined;
    const onMessage = (event: MessageEvent): void => {
      if (event.source === null || event.source !== iframeRef.current?.contentWindow) return;
      if (event.origin !== "null") return;
      const message = parseSandboxMessage(event.data);
      if (message === null) return;
      if (message.type === MSG_READY) {
        readyRef.current = true;
        send();
      } else if (message.request_id === requestRef.current) {
        setStatus(message.type === MSG_RENDERED ? "rendered" : "failed");
        if (message.type === MSG_ERROR) setView("table");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [rejected, send]);

  // Focus moving into the framed document blurs the host window while the iframe element becomes
  // the host's active element; focus coming back to the host fires window focus.
  useEffect(() => {
    const sync = (): void => setFrameFocused(document.activeElement === iframeRef.current);
    const clear = (): void => setFrameFocused(false);
    window.addEventListener("blur", sync);
    window.addEventListener("focus", clear);
    return () => {
      window.removeEventListener("blur", sync);
      window.removeEventListener("focus", clear);
    };
  }, []);

  // Plan changed while the sandbox is already ready: render the new plan.
  useEffect(() => {
    send();
  }, [send]);

  const shown = rejected ? "table" : view;
  return (
    <div
      className={mergeClasses(
        styles.root,
        treatment.panelSurface === "lifted" && styles.lifted,
        treatment.surface === "raised" && styles.raised,
        treatment.border === "strong" && styles.strong,
        treatment.radius === "small" ? styles.radiusSmall : styles.radiusMedium,
      )}
      data-testid="chart-frame"
    >
      <TabList
        selectedValue={shown}
        onTabSelect={(_, data) => setView(data.value === "table" ? "table" : "chart")}
        aria-label={STRINGS.viewLabel}
        size="small"
      >
        <Tab value="chart" disabled={rejected}>
          {STRINGS.chartView}
        </Tab>
        <Tab value="table">{STRINGS.tableView}</Tab>
      </TabList>
      {rejected ? (
        <ErrorState title={STRINGS.rejected} />
      ) : (
        <div hidden={shown !== "chart"}>
          <iframe
            ref={iframeRef}
            className={mergeClasses(styles.frame, frameFocused && styles.frameFocused)}
            title={title}
            src={sandboxSrc}
            sandbox="allow-scripts"
            // Chromium matches neither :focus nor :focus-visible on an iframe whose document holds
            // focus, so the ring is driven by the focus and blur events the iframe element gets.
            onFocus={() => setFrameFocused(true)}
            onBlur={() => setFrameFocused(false)}
            onLoad={() => {
              // The sandbox script has run before load; covers a missed ready message.
              readyRef.current = true;
              send();
            }}
            referrerPolicy="no-referrer"
            style={{ height }}
          />
          {status === "loading" ? <div role="status">{STRINGS.loading}</div> : null}
        </div>
      )}
      {!rejected && status === "failed" ? <ErrorState title={STRINGS.failed} /> : null}
      {shown === "table" ? <ChartTable plan={plan} caption={title} /> : null}
      <Text size={200} className={styles.sources} data-testid="chart-sources">
        {STRINGS.sources}:{" "}
        {plan.citations.map((c, i) => (
          <span key={`${c.evidence_id}|${i}`}>
            {i > 0 ? "; " : ""}
            {c.label ?? c.evidence_id} ({STRINGS.asOf} <Timestamp value={c.as_of} />)
          </span>
        ))}
      </Text>
    </div>
  );
}
