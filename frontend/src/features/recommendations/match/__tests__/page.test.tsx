import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  COLD_ID,
  DOMAIN,
  ResizeObserverStub,
  TASK,
  WARM_ID,
  json,
  problem,
  setupPage,
  view,
  type Behaviour,
} from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});

async function submit(b: Behaviour = {}) {
  const user = userEvent.setup();
  const page = setupPage(b);
  await user.type(await screen.findByTestId("match-task-input"), TASK);
  await user.click(screen.getByTestId("match-submit"));
  return { user, ...page };
}

describe("FindAgentPage", () => {
  it("renders ranked cards best first with score, confidence and explanation", async () => {
    await submit();
    const cards = await screen.findAllByTestId("match-candidate");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute("data-entity-id", WARM_ID);
    expect(within(cards[0]!).getByText("Invoice Summarizer")).toBeInTheDocument();
    expect(within(cards[0]!).getByTestId("match-score")).toHaveTextContent("0.71");
    expect(within(cards[0]!).getByTestId("match-confidence")).toHaveTextContent("0.86");
    expect(within(cards[0]!).getAllByTestId("match-signal")).toHaveLength(8);
    expect(screen.getByTestId("match-confidence-note")).toHaveTextContent("not a probability");
    expect(screen.getByRole("heading", { name: "Find an agent" })).toBeInTheDocument();
  });

  it("states unobserved signals in words and labels cold start", async () => {
    await submit({
      match: () => json(view({ cold_start: true, signals_unavailable: ["latency"] })),
    });
    const cards = await screen.findAllByTestId("match-candidate");
    const cold = cards[1]!;
    expect(within(cold).getByTestId("match-cold-start")).toBeInTheDocument();
    expect(within(cold).getAllByText("No telemetry yet")).toHaveLength(3);
    expect(within(cold).getAllByText("Not counted")).toHaveLength(3);
    expect(screen.getByTestId("match-cold-start-banner")).toHaveTextContent("Latency");
  });

  it("shows partial banner with the reason and announces it", async () => {
    await submit({ match: () => json(view({ truncated: true, partial_reason: "limit" })) });
    expect(await screen.findByTestId("match-partial")).toHaveTextContent(
      "Result limit reached; more candidates exist",
    );
    expect(screen.getByTestId("match-status")).toHaveTextContent("2 results. Partial results");
  });

  it("shows an empty state for no candidates", async () => {
    await submit({ match: () => json(view({ candidates: [] })) });
    expect(await screen.findByTestId("match-empty")).toHaveTextContent("broader wording");
    expect(screen.getByTestId("match-status")).toHaveTextContent("No results");
  });

  it("shows the shared error state with the reason code on 403 and 503", async () => {
    await submit({ match: () => problem(403, "forbidden", "data_read_required") });
    expect(await screen.findByTestId("forbidden-state")).toBeInTheDocument();
    expect(screen.getByTestId("match-error-reason")).toHaveTextContent("data_read_required");
    cleanup();
    await submit({ match: () => problem(503, "capability_unavailable", "matcher_disabled") });
    expect(await screen.findByTestId("unavailable-state")).toBeInTheDocument();
    expect(screen.getByTestId("match-error-reason")).toHaveTextContent("matcher_disabled");
  });

  it("accepts once, confirms after the 202, and lets the decision change", async () => {
    const { user, fetchImpl } = await submit();
    const card = (await screen.findAllByTestId("match-candidate"))[0]!;
    const accept = within(card).getByTestId("match-accept");
    await user.click(accept);
    await waitFor(() =>
      expect(within(card).getByTestId("match-decision")).toHaveTextContent("Accepted"),
    );
    expect(accept).toHaveAttribute("aria-pressed", "true");
    const posts = fetchImpl.mock.calls.filter((c) => String(c[0]).endsWith("/match/feedback"));
    expect(posts).toHaveLength(1);
    expect(JSON.parse(String(posts[0]![1]?.body))).toMatchObject({
      match_id: "m-1",
      entity_id: WARM_ID,
      decision: "accepted",
    });
    await user.click(within(card).getByTestId("match-reject"));
    await waitFor(() =>
      expect(within(card).getByTestId("match-decision")).toHaveTextContent("Rejected"),
    );
    expect(card.contains(document.activeElement)).toBe(true);
  });

  it("keeps the previous state and shows the error when feedback fails", async () => {
    const { user } = await submit({ feedback: () => problem(503, "dependency_transient", "down") });
    const card = (await screen.findAllByTestId("match-candidate"))[1]!;
    await user.click(within(card).getByTestId("match-accept"));
    expect(await within(card).findByTestId("match-feedback-error")).toBeInTheDocument();
    expect(within(card).getByTestId("match-decision")).toHaveTextContent("No decision yet");
    expect(within(card).getByTestId("match-accept")).toHaveAttribute("aria-pressed", "false");
    expect(card.contains(document.activeElement)).toBe(true);
  });

  it("never writes the task text to the URL, storage or the console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m),
    );
    const { router } = await submit();
    await screen.findAllByTestId("match-candidate");
    expect(router.state.location.search).not.toContain("Summarize");
    expect(decodeURIComponent(router.state.location.search)).not.toContain(TASK);
    expect(JSON.stringify({ ...localStorage })).not.toContain("Summarize");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("Summarize");
    for (const s of spies) {
      expect(JSON.stringify(s.mock.calls)).not.toContain("Summarize");
      s.mockRestore();
    }
  });

  it("asks for a domain when none is selected", async () => {
    setupPage({}, "/recommendations/find");
    expect(await screen.findByTestId("domain-required")).toBeInTheDocument();
  });

  it("posts the match to the domain path without a scope parameter", async () => {
    const { fetchImpl } = await submit();
    await screen.findAllByTestId("match-candidate");
    const call = fetchImpl.mock.calls.find(
      (c) => String(c[0]).endsWith("/match") && c[1]?.method === "POST",
    );
    expect(String(call![0])).toContain(encodeURIComponent(DOMAIN));
    expect(JSON.parse(String(call![1]?.body))).toEqual({
      schema_version: "1.0.0",
      task_text: TASK,
    });
    expect(COLD_ID).toBeTruthy();
  });
});
