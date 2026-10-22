import { useCallback, useEffect, useRef, useState } from "react";
import { isApiError } from "../../api/errors.js";
import { STRINGS } from "./strings";
import { createConversation, streamMessage, type StreamTransport } from "./stream";
import { applyEvent, failTurn, newTurn } from "./turns";
import type { AssistantTurn, ContextEcho, MessageContext } from "./types";

export interface CopilotChat {
  readonly turns: readonly AssistantTurn[];
  /** The `context` event of the latest turn: what the server says it received. */
  readonly echo: ContextEcho | null;
  readonly busy: boolean;
  readonly send: (text: string, context: MessageContext) => Promise<void>;
}

function mark(name: string): void {
  if (typeof performance !== "undefined" && typeof performance.mark === "function") {
    performance.mark(name);
  }
}

function measure(name: string, start: string, end: string): void {
  if (typeof performance !== "undefined" && typeof performance.measure === "function") {
    try {
      performance.measure(name, start, end);
    } catch {
      // A missing mark only loses a timing entry, never the chat.
    }
  }
}

function describe(error: unknown): { code: string; detail: string } {
  if (isApiError(error)) {
    const detail = STRINGS.httpErrors[error.code] ?? STRINGS.httpErrors["unexpected_response"];
    return { code: error.code, detail: detail ?? STRINGS.httpErrors["unexpected_response"] ?? "" };
  }
  return { code: "unexpected_response", detail: STRINGS.httpErrors["unexpected_response"] ?? "" };
}

/**
 * Chat state and the streaming loop. One conversation per mount; a new message aborts the one in
 * flight, and unmounting aborts too. Nothing here can execute an action: the only endpoints
 * touched are conversation create and message post.
 */
export function useCopilotChat(transport: StreamTransport | null): CopilotChat {
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [echo, setEcho] = useState<ContextEcho | null>(null);
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const counter = useRef(0);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const patch = useCallback((key: string, update: (turn: AssistantTurn) => AssistantTurn) => {
    setTurns((all) => all.map((t) => (t.key === key ? update(t) : t)));
  }, []);

  const send = useCallback(
    async (text: string, context: MessageContext): Promise<void> => {
      const trimmed = text.trim();
      if (trimmed === "") return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      counter.current += 1;
      const n = counter.current;
      const key = `turn-${n}`;
      // A message sent while another is streaming ends the earlier one as stopped.
      setTurns((all) => [
        ...all.map((t) => failTurn(t, "cancelled", STRINGS.cancelled)),
        newTurn(key, trimmed),
      ]);
      setBusy(true);
      if (transport === null) {
        patch(key, (t) =>
          failTurn(t, "unavailable", STRINGS.httpErrors["unexpected_response"] ?? ""),
        );
        setBusy(false);
        return;
      }
      const startMark = `copilot:send:${n}`;
      mark(startMark);
      const startedAt = performance.now();
      let sawToken = false;
      try {
        if (conversationId.current === null) {
          conversationId.current = (await createConversation(transport, controller.signal)).id;
        }
        for await (const event of streamMessage(
          transport,
          conversationId.current,
          { text: trimmed, context },
          controller.signal,
        )) {
          if (controller.signal.aborted) return;
          if (event.name === "context") setEcho(event.data);
          let firstTokenMs: number | null = null;
          if (event.name === "token" && !sawToken) {
            sawToken = true;
            firstTokenMs = performance.now() - startedAt;
            mark(`copilot:first-token:${n}`);
            measure(`copilot:first-token-latency:${n}`, startMark, `copilot:first-token:${n}`);
          }
          patch(key, (t) => applyEvent(t, event, firstTokenMs));
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        // An expired or foreign conversation is a 404: start a fresh one next time.
        if (isApiError(error) && error.status === 404) conversationId.current = null;
        const { code, detail } = describe(error);
        patch(key, (t) => failTurn(t, code, detail));
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setBusy(false);
        }
      }
    },
    [transport, patch],
  );

  return { turns, echo, busy, send };
}
