import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { registerTokenSource } from "../auth/token";
import {
  LAST_DOMAIN_KEY_PREFIX,
  NO_DOMAINS_MESSAGE,
  lastDomainStorageKey,
  pseudonymousUserKey,
} from "./domain";
import {
  accountWith,
  domainEntry,
  problemResponse,
  renderShell,
  stubResizeObserver,
} from "./test-support";

const FINANCE = "commercial:t:sandbox:domain:finance";
const OPS = "commercial:t:sandbox:domain:ops";
const NAMELESS = "commercial:t:sandbox:domain:nameless";

const LIST = [
  domainEntry(FINANCE, "Finance"),
  domainEntry(NAMELESS, "Nameless", "derived"),
  domainEntry(OPS, "Operations"),
];

function ok(items = LIST): () => Response {
  return () => new Response(JSON.stringify({ items }), { status: 200 });
}

beforeAll(stubResizeObserver);
beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

function newAccount() {
  return accountWith(`home-${crypto.randomUUID()}`, ["Viewer"]);
}

async function chooseDomain(name: string | RegExp): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("combobox", { name: "Domain" }));
  await user.click(await screen.findByRole("option", { name }));
}

describe("domain switcher", () => {
  it("lists display names and labels an ID-only fallback as name unavailable", async () => {
    renderShell({ account: newAccount(), respond: ok() });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: "Domain" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["Finance", `${NAMELESS} (name unavailable)`, "Operations"]);
  });

  it("selecting a domain sets ?domain_id= and every nav link carries it", async () => {
    const { router } = renderShell({ account: newAccount(), respond: ok() });
    await chooseDomain("Operations");
    await waitFor(() =>
      expect(router.state.location.search).toBe(`?domain_id=${encodeURIComponent(OPS)}`),
    );
    expect(router.state.location.pathname).toBe("/page");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      `/?domain_id=${encodeURIComponent(OPS)}`,
      `/page?domain_id=${encodeURIComponent(OPS)}`,
    ]);
  });

  it("shows the first readable domain when nothing is in the URL or storage", async () => {
    renderShell({ account: newAccount(), respond: ok() });
    const box = await screen.findByRole("combobox", { name: "Domain" });
    await waitFor(() => expect(box).toHaveTextContent("Finance"));
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Some page" }).getAttribute("href")).toBe(
      `/page?domain_id=${encodeURIComponent(FINANCE)}`,
    );
  });

  it("keeps a domain from the URL as the source of truth", async () => {
    renderShell({
      account: newAccount(),
      respond: ok(),
      path: `/page?domain_id=${encodeURIComponent(OPS)}`,
    });
    const box = await screen.findByRole("combobox", { name: "Domain" });
    await waitFor(() => expect(box).toHaveTextContent("Operations"));
  });

  it("shows No domains are assigned to you on 403", async () => {
    renderShell({ account: newAccount(), respond: () => problemResponse(403) });
    expect(await screen.findByText(NO_DOMAINS_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Domain" })).toBeNull();
  });

  it("says the list could not be loaded on other failures, without claiming no domains", async () => {
    renderShell({ account: newAccount(), respond: () => problemResponse(500) });
    expect(await screen.findByText("Domains could not be loaded")).toBeInTheDocument();
    expect(screen.queryByText(NO_DOMAINS_MESSAGE)).toBeNull();
  });
});

describe("empty domain list", () => {
  it("shows the no-domains message for a 200 with no items and invents no domain", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { router } = renderShell({ account: newAccount(), respond: ok([]) });
    expect(await screen.findByText(NO_DOMAINS_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Domain" })).toBeNull();
    expect(router.state.location.search).toBe("");
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
  });
});

describe("default domain in the URL", () => {
  it("replaces a missing domain_id with the default, keeping other params and the hash", async () => {
    const { router } = renderShell({ account: newAccount(), respond: ok(), path: "/page?x=1#frag" });
    await waitFor(() => expect(router.state.location.search).toContain("domain_id="));
    const params = new URLSearchParams(router.state.location.search);
    expect(params.get("domain_id")).toBe(FINANCE);
    expect(params.get("x")).toBe("1");
    expect(router.state.location.hash).toBe("#frag");
    // A replace, not a push: the history action is REPLACE and the entry count did not grow.
    expect(router.state.historyAction).toBe("REPLACE");
    expect(localStorage.length).toBe(0);
  });

  it("uses the remembered domain as the default", async () => {
    const account = newAccount();
    const userKey = await pseudonymousUserKey(account.homeAccountId);
    localStorage.setItem(lastDomainStorageKey(userKey ?? ""), OPS);
    const { router } = renderShell({ account, respond: ok() });
    await waitFor(() =>
      expect(router.state.location.search).toBe(`?domain_id=${encodeURIComponent(OPS)}`),
    );
  });

  it("never touches a domain_id that is present, readable or not", async () => {
    const gone = "commercial:t:sandbox:domain:gone";
    for (const id of [OPS, gone]) {
      const path = `/page?domain_id=${encodeURIComponent(id)}`;
      const { router } = renderShell({ account: newAccount(), respond: ok(), path });
      await screen.findByRole("combobox", { name: "Domain" });
      expect(router.state.location.search).toBe(`?domain_id=${encodeURIComponent(id)}`);
      expect(router.state.historyAction).toBe("POP");
      cleanup();
    }
  });

  it("rewrites exactly once and does not loop", async () => {
    const { router } = renderShell({ account: newAccount(), respond: ok() });
    const navigate = vi.spyOn(router, "navigate");
    await waitFor(() => expect(router.state.location.search).toContain("domain_id="));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(router.state.location.search).toBe(`?domain_id=${encodeURIComponent(FINANCE)}`);
  });

  it("does not rewrite when the list could not be loaded", async () => {
    const { router } = renderShell({ account: newAccount(), respond: () => problemResponse(403) });
    await screen.findByText(NO_DOMAINS_MESSAGE);
    expect(router.state.location.search).toBe("");
  });
});

describe("last selected domain in localStorage", () => {
  it("stores the domain id only, under a pseudonymous key, and nothing else", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const account = newAccount();
    renderShell({ account, respond: ok() });
    await chooseDomain("Operations");

    const userKey = await pseudonymousUserKey(account.homeAccountId);
    expect(userKey).toMatch(/^[0-9a-f]{32}$/);
    const key = lastDomainStorageKey(userKey ?? "");
    await waitFor(() => expect(setItem).toHaveBeenCalledWith(key, OPS));

    // Every write to localStorage is that one key with that one value.
    expect(setItem.mock.calls).toEqual([[key, OPS]]);
    expect(localStorage.length).toBe(1);
    expect(localStorage.key(0)).toBe(key);
    // The raw account id and e-mail never appear in storage.
    const dump = JSON.stringify({ ...localStorage });
    expect(dump).not.toContain(account.homeAccountId);
    expect(dump).not.toContain(account.username);
    expect(key.startsWith(LAST_DOMAIN_KEY_PREFIX)).toBe(true);
  });

  it("writes nothing to localStorage just by loading the shell", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    renderShell({ account: newAccount(), respond: ok() });
    await screen.findByRole("combobox", { name: "Domain" });
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
  });

  it("restores the remembered domain when it is still readable", async () => {
    const account = newAccount();
    const userKey = await pseudonymousUserKey(account.homeAccountId);
    localStorage.setItem(lastDomainStorageKey(userKey ?? ""), OPS);
    renderShell({ account, respond: ok() });
    const box = await screen.findByRole("combobox", { name: "Domain" });
    await waitFor(() => expect(box).toHaveTextContent("Operations"));
  });

  it("falls back to the first readable domain when the remembered one is gone", async () => {
    const account = newAccount();
    const userKey = await pseudonymousUserKey(account.homeAccountId);
    localStorage.setItem(lastDomainStorageKey(userKey ?? ""), "commercial:t:sandbox:domain:gone");
    renderShell({ account, respond: ok() });
    const box = await screen.findByRole("combobox", { name: "Domain" });
    await waitFor(() => expect(box).toHaveTextContent("Finance"));
  });

  it("is cleared on sign-out", async () => {
    const account = newAccount();
    const userKey = await pseudonymousUserKey(account.homeAccountId);
    const key = lastDomainStorageKey(userKey ?? "");
    localStorage.setItem(key, OPS);
    const { msal } = renderShell({ account, respond: ok() });
    registerTokenSource(msal, "api://test/access");
    const user = userEvent.setup();
    await screen.findByRole("combobox", { name: "Domain" });
    await user.click(screen.getByRole("button", { name: /^Account:/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    expect(localStorage.getItem(key)).toBeNull();
    expect(localStorage.length).toBe(0);
    expect(vi.mocked(msal.logoutRedirect)).toHaveBeenCalledTimes(1);
  });
});
