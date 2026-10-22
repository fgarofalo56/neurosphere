import type { AssistantTurn, CopilotEvent } from "./types";

export function newTurn(key: string, userText: string): AssistantTurn {
  return {
    key,
    userText,
    status: "streaming",
    text: "",
    tools: [],
    citations: [],
    charts: [],
    chartQuerySpecs: [],
    suggestions: [],
    reason: null,
    failure: null,
    firstTokenMs: null,
  };
}

/**
 * Folds one event into the turn. A turn that already ended ignores further events.
 *
 * `abstain` and `denied` DISCARD everything streamed so far (tokens, citations, charts,
 * suggestions): the contract says text streamed before them is never an answer, so the UI shows
 * only the abstention or denial message with its reason.
 */
export function applyEvent(
  turn: AssistantTurn,
  event: CopilotEvent,
  firstTokenMs: number | null = null,
): AssistantTurn {
  if (turn.status !== "streaming") return turn;
  switch (event.name) {
    case "context":
      return turn;
    case "tool": {
      // A status update for a tool replaces its earlier entry.
      const rest = turn.tools.filter((t) => t.name !== event.data.name);
      return { ...turn, tools: [...rest, event.data] };
    }
    case "token":
      return {
        ...turn,
        text: turn.text + event.data.text,
        firstTokenMs: turn.firstTokenMs ?? firstTokenMs,
      };
    case "citation":
      return { ...turn, citations: [...turn.citations, event.data] };
    case "chart":
      return {
        ...turn,
        charts: [...turn.charts, event.data.chart_plan],
        chartQuerySpecs: [...turn.chartQuerySpecs, event.data.query_spec ?? null],
      };
    case "action_suggestion":
      return { ...turn, suggestions: [...turn.suggestions, event.data] };
    case "done":
      return { ...turn, status: "answered" };
    case "abstain":
      return discard(turn, "abstain", event.data);
    case "denied":
      return discard(turn, "denied", event.data);
    case "error":
      return { ...turn, status: "error", failure: event.data };
  }
}

function discard(
  turn: AssistantTurn,
  status: "abstain" | "denied",
  reason: NonNullable<AssistantTurn["reason"]>,
): AssistantTurn {
  return {
    ...turn,
    status,
    text: "",
    citations: [],
    charts: [],
    chartQuerySpecs: [],
    suggestions: [],
    reason,
  };
}

export function failTurn(turn: AssistantTurn, code: string, detail: string): AssistantTurn {
  if (turn.status !== "streaming") return turn;
  return { ...turn, status: "error", failure: { code, detail } };
}
