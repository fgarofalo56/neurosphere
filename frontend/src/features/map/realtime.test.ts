import { describe, expect, it, vi } from "vitest";
import { createBurstDebouncer } from "./hooks";
import { parseServerMessage } from "./realtime";

const TOPOLOGY = {
  type: "topology",
  domain_id: "d1",
  seq: 7,
  changed_at: "2026-11-24T10:00:00Z",
  change_kinds: ["node_added", "edge_added"],
  entity_ids: ["commercial:c:s:agent:a"],
  refetch: true,
  truncated: false,
  emitted_at: "2026-11-24T10:00:01Z",
};

describe("topology message", () => {
  it("parses the change notice", () => {
    const message = parseServerMessage(JSON.stringify(TOPOLOGY));
    expect(message.kind).toBe("topology");
    if (message.kind !== "topology") return;
    expect(message.topology).toMatchObject({
      type: "topology",
      domain_id: "d1",
      seq: 7,
      change_kinds: ["node_added", "edge_added"],
      entity_ids: ["commercial:c:s:agent:a"],
      refetch: true,
      truncated: false,
    });
  });

  it("ignores a frame without a domain or sequence", () => {
    expect(parseServerMessage(JSON.stringify({ ...TOPOLOGY, domain_id: 3 })).kind).toBe("ignored");
    expect(parseServerMessage(JSON.stringify({ ...TOPOLOGY, seq: "x" })).kind).toBe("ignored");
  });

  it("treats an unreadable notice as a refetch rather than missing a change", () => {
    const message = parseServerMessage(JSON.stringify({ ...TOPOLOGY, refetch: "yes" }));
    expect(message.kind === "topology" && message.topology.refetch).toBe(true);
  });
});

describe("createBurstDebouncer", () => {
  it("runs once for a burst, after it goes quiet", () => {
    vi.useFakeTimers();
    try {
      const run = vi.fn();
      const burst = createBurstDebouncer(run, 400, 2000);
      for (let i = 0; i < 5; i += 1) {
        burst.trigger();
        vi.advanceTimersByTime(100);
      }
      expect(run).not.toHaveBeenCalled();
      vi.advanceTimersByTime(400);
      expect(run).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(5000);
      expect(run).toHaveBeenCalledTimes(1);
      burst.trigger(); // a later burst runs again
      vi.advanceTimersByTime(400);
      expect(run).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("still runs during a steady stream (max wait) and can be cancelled", () => {
    vi.useFakeTimers();
    try {
      const run = vi.fn();
      const burst = createBurstDebouncer(run, 400, 2000);
      for (let i = 0; i < 30; i += 1) {
        burst.trigger();
        vi.advanceTimersByTime(100);
      }
      expect(run).toHaveBeenCalledTimes(1);
      burst.trigger();
      burst.cancel();
      vi.advanceTimersByTime(5000);
      expect(run).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
