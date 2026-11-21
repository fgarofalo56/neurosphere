import { render, screen, cleanup, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { QueryProvider } from "../../../../api/index.js";
import { ExplanationList } from "../ExplanationList";
import { MatchCandidateCard, entityHref, mapHref } from "../MatchCandidateCard";
import { joinAssessments } from "../types";
import { COLD_ID, DOMAIN, ResizeObserverStub, WARM_ID, makeClient, view } from "./fixtures";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});
afterEach(cleanup);

function renderCard(index: number, assessments = view().assessments) {
  const v = { ...view(), assessments };
  const item = joinAssessments(v)[index]!;
  const { client, queryClient } = makeClient({});
  render(
    <MemoryRouter>
      <QueryProvider client={client} queryClient={queryClient}>
        <ul>
          <MatchCandidateCard
            item={item}
            domainId={DOMAIN}
            matchId="m-1"
            decision={undefined}
            onConfirmed={() => {}}
          />
        </ul>
      </QueryProvider>
    </MemoryRouter>,
  );
}

describe("MatchCandidateCard", () => {
  it("shows kind, cold start and links to catalog and map", () => {
    renderCard(1);
    const card = screen.getByTestId("match-candidate");
    expect(within(card).getByText("Tool")).toBeInTheDocument();
    expect(within(card).getByTestId("match-cold-start")).toHaveTextContent("Cold start");
    expect(within(card).getByRole("link", { name: "Open in catalog" })).toHaveAttribute(
      "href",
      entityHref(COLD_ID),
    );
    expect(within(card).getByRole("link", { name: "Show on map" })).toHaveAttribute(
      "href",
      mapHref(DOMAIN),
    );
    expect(mapHref(DOMAIN).startsWith("/map?domain_id=")).toBe(true);
    expect(entityHref(COLD_ID).startsWith("/catalog/entity?entity_id=")).toBe(true);
  });

  it("lists graph relationships with links, or says none", () => {
    renderCard(0);
    expect(screen.getByTestId("match-relations")).toHaveTextContent("uses_model (outgoing)");
    cleanup();
    renderCard(1);
    expect(screen.getByTestId("match-no-relations")).toBeInTheDocument();
  });

  it("shows 'not available' for a missing assessment, never 0", () => {
    renderCard(0, []);
    expect(screen.getByTestId("match-confidence")).toHaveTextContent("Not available");
    expect(screen.getByTestId("match-confidence")).not.toHaveTextContent("0");
    expect(screen.queryByTestId("match-cold-start")).toBeNull();
    expect(WARM_ID).toBeTruthy();
  });
});

describe("ExplanationList", () => {
  it("renders one row per signal and no zero for unobserved values", () => {
    render(<ExplanationList signals={view().match.candidates[1]!.signals} />);
    const rows = screen.getAllByTestId("match-signal");
    expect(rows).toHaveLength(8);
    const unobserved = rows.filter((r) => r.getAttribute("data-observed") === "false");
    expect(unobserved).toHaveLength(3);
    for (const r of unobserved) {
      expect(r).toHaveTextContent("No telemetry yet");
      expect(r).toHaveTextContent("Not counted");
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
  });
});
