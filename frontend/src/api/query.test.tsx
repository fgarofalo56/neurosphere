import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createApiClient } from "./client.js";
import { ForbiddenError } from "./errors.js";
import { QueryProvider, createQueryHook } from "./query.js";

const useThing = createQueryHook<{ id: string }, { name: string }>({
  key: "thing",
  fetcher: (client, params, signal) => client.get(`/v1/things/${params.id}`, undefined, signal),
});

function Thing() {
  const q = useThing({ id: "1" });
  if (q.error) return <p>error:{q.error.code}</p>;
  if (q.data) return <p>data:{q.data.name}</p>;
  return <p>loading</p>;
}

function clientFor(response: () => Response) {
  return createApiClient({
    baseUrl: "http://x",
    getToken: () => Promise.resolve("t"),
    fetchImpl: (() => Promise.resolve(response())) as typeof fetch,
  });
}

describe("createQueryHook", () => {
  it("renders data on success", async () => {
    const client = clientFor(() => new Response(JSON.stringify({ name: "n" }), { status: 200 }));
    render(
      <QueryProvider client={client}>
        <Thing />
      </QueryProvider>,
    );
    await waitFor(() => expect(screen.getByText("data:n")).toBeTruthy());
  });

  it("surfaces a 403 as a typed error, not empty data", async () => {
    const client = clientFor(
      () => new Response(JSON.stringify({ code: "forbidden", status: 403 }), { status: 403 }),
    );
    render(
      <QueryProvider client={client}>
        <Thing />
      </QueryProvider>,
    );
    await waitFor(() => expect(screen.getByText("error:forbidden")).toBeTruthy());
    expect(ForbiddenError.name).toBe("ForbiddenError");
  });
});
