import type { ChartPlan } from "@neurosphere/contracts";

export type { ChartPlan };

/** Hand-mirrored from services/api/neurosphere_api/copilot/models.py (PRP-19 wire contract). */
export type Freshness = "fresh" | "stale" | "unknown";
export type FilterValue = string | readonly string[];

export interface TimeRangeValue {
  readonly from: string;
  readonly to: string;
}

/** What the browser asks to be used as context. A hint: the server can only narrow it. */
export interface MessageContext {
  readonly page: string | null;
  readonly route: string | null;
  readonly filters: Readonly<Record<string, FilterValue>>;
  readonly time_range: TimeRangeValue | null;
  readonly selection: readonly string[];
  readonly domain_id: string | null;
}

export interface MessageBody {
  readonly text: string;
  readonly context: MessageContext;
}

export interface ConversationCreated {
  readonly id: string;
  readonly created_at: string;
  readonly retention_class: string;
  readonly expires_at: string;
}

/** The `context` event: exactly what the copilot received. Drives the context chip. */
export interface ContextEcho {
  readonly page: string | null;
  readonly route: string | null;
  readonly filters: Readonly<Record<string, FilterValue>>;
  readonly time_range: TimeRangeValue | null;
  readonly selection: readonly string[];
  readonly dropped_selection_count: number;
  readonly applied_domains: readonly string[];
}

export interface ToolEvent {
  readonly name: string;
  readonly status: "started" | "ok" | "refused";
}

export interface CitationEvent {
  readonly record_id: string;
  readonly kind: string;
  readonly source: string;
  readonly as_of: string | null;
  readonly freshness: Freshness;
}

export interface ActionSuggestionEvent {
  readonly intent_id: string;
  readonly domain_id: string;
  readonly action_type: string;
  readonly target: Readonly<Record<string, unknown>>;
  readonly intent_hash: string;
}

export interface TerminalReason {
  readonly message_id: string;
  readonly reason_code: string;
  readonly reason: string;
}

/** One parsed server-sent event. Unknown event names never reach this type. */
export type CopilotEvent =
  | { readonly name: "context"; readonly data: ContextEcho }
  | { readonly name: "tool"; readonly data: ToolEvent }
  | { readonly name: "token"; readonly data: { readonly text: string } }
  | { readonly name: "citation"; readonly data: CitationEvent }
  | { readonly name: "chart"; readonly data: { readonly chart_plan: ChartPlan } }
  | { readonly name: "action_suggestion"; readonly data: ActionSuggestionEvent }
  | {
      readonly name: "done";
      readonly data: { readonly message_id: string; readonly status: "answered" };
    }
  | { readonly name: "abstain"; readonly data: TerminalReason }
  | { readonly name: "denied"; readonly data: TerminalReason }
  | {
      readonly name: "error";
      readonly data: { readonly code: string; readonly detail: string };
    };

export type TurnStatus = "streaming" | "answered" | "abstain" | "denied" | "error";

/** The assistant side of one exchange, folded from the event stream. */
export interface AssistantTurn {
  readonly key: string;
  readonly userText: string;
  readonly status: TurnStatus;
  /** Streamed tokens. Emptied when the turn ends in `abstain` or `denied`. */
  readonly text: string;
  readonly tools: readonly ToolEvent[];
  readonly citations: readonly CitationEvent[];
  readonly charts: readonly ChartPlan[];
  readonly suggestions: readonly ActionSuggestionEvent[];
  /** Set for `abstain` and `denied`. */
  readonly reason: TerminalReason | null;
  /** Set for `error` (stream event or HTTP failure). */
  readonly failure: { readonly code: string; readonly detail: string } | null;
  /** Milliseconds from send to the first `token` event (test instrumentation). */
  readonly firstTokenMs: number | null;
}
