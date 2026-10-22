/**
 * Entry of the sandboxed chart document (chart-sandbox.html). Runs in an opaque origin with no
 * network. Talks to the parent only through postMessage and accepts messages only from it.
 */
import {
  MSG_ERROR,
  MSG_READY,
  MSG_RENDERED,
  PROTOCOL_VERSION,
  parseParentMessage,
  type ChartErrorCode,
  type SandboxToParent,
} from "../protocol";
import { InvalidSpecError, renderSpec } from "./render";

const container = document.getElementById("chart");
let current: { finalize(): void } | null = null;

function send(message: SandboxToParent): void {
  // The parent origin is unknown from an opaque origin; messages carry no data.
  window.parent.postMessage(message, "*");
}

function fail(requestId: string, code: ChartErrorCode): void {
  send({ type: MSG_ERROR, version: PROTOCOL_VERSION, request_id: requestId, code });
}

window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== window.parent) return;
  const message = parseParentMessage(event.data);
  if (message === null || container === null) return;
  current?.finalize();
  current = null;
  container.replaceChildren();
  renderSpec(message.spec, container).then(
    (view) => {
      current = view;
      send({
        type: MSG_RENDERED,
        version: PROTOCOL_VERSION,
        request_id: message.request_id,
      });
    },
    (error: unknown) => {
      fail(
        message.request_id,
        error instanceof InvalidSpecError ? "invalid_spec" : "render_failed",
      );
    },
  );
});

send({ type: MSG_READY, version: PROTOCOL_VERSION });
