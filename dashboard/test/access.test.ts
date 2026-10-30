import { describe, expect, it } from "vitest";
import { access, canView, isDocsPath, parseViewers } from "../lib/access";

describe("parseViewers", () => {
  it("lowercases, trims and drops blanks", () => {
    expect(parseViewers(" Octo-Cat, b ,,C")).toEqual(new Set(["octo-cat", "b", "c"]));
  });

  it("is empty when unset, empty or only separators", () => {
    expect(parseViewers(undefined).size).toBe(0);
    expect(parseViewers("").size).toBe(0);
    expect(parseViewers(" , ,").size).toBe(0);
  });
});

describe("canView", () => {
  const viewers = parseViewers("A, b ,,");

  it("matches logins in any case", () => {
    expect(canView("a", viewers)).toBe(true);
    expect(canView("B", viewers)).toBe(true);
  });

  it("refuses others, prefixes and no login", () => {
    expect(canView("c", viewers)).toBe(false);
    expect(canView("ab", viewers)).toBe(false);
    expect(canView("", viewers)).toBe(false);
    expect(canView(null, viewers)).toBe(false);
    expect(canView(undefined, viewers)).toBe(false);
  });
});

describe("access", () => {
  it("lets nobody in when DOCS_VIEWERS is unset or empty", () => {
    expect(access("octo", undefined)).toEqual({ state: "denied", login: "octo" });
    expect(access("octo", "")).toEqual({ state: "denied", login: "octo" });
    expect(access("octo", "  ")).toEqual({ state: "denied", login: "octo" });
  });

  it("treats a visitor without a session as signed out, whatever the list", () => {
    expect(access(null, "octo")).toEqual({ state: "signed-out" });
    expect(access(undefined, undefined)).toEqual({ state: "signed-out" });
    expect(access("", "octo")).toEqual({ state: "signed-out" });
  });

  it("allows listed logins and names the denied one", () => {
    expect(access("Octo", "hubot, octo")).toEqual({ state: "allowed", login: "Octo" });
    expect(access("mona", "hubot, octo")).toEqual({ state: "denied", login: "mona" });
  });
});

describe("isDocsPath", () => {
  it("covers /docs and its pages, not the home page", () => {
    for (const p of ["/docs", "/docs/", "/docs/how-it-works"]) expect(isDocsPath(p)).toBe(true);
    for (const p of ["/", "/projects", "/docsy", "/octo/docs", "/access", "/api/auth/login"]) expect(isDocsPath(p)).toBe(false);
  });
});
