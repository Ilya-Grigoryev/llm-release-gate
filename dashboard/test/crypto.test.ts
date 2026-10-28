import { createHmac, generateKeyPairSync, createVerify } from "node:crypto";
import { describe, expect, it } from "vitest";
import { appJwt, signed } from "../lib/github";
import { safeNext, seal, unseal } from "../lib/session";

describe("seal", () => {
  it("round-trips and refuses a changed value or another secret", () => {
    const value = seal({ login: "octo", token: "t" }, "s1");
    expect(unseal(value, "s1")).toEqual({ login: "octo", token: "t" });
    expect(unseal(value, "s2")).toBeNull();
    const flipped = Buffer.from(value, "base64url");
    flipped[flipped.length - 1] ^= 1;
    expect(unseal(flipped.toString("base64url"), "s1")).toBeNull();
    expect(unseal("", "s1")).toBeNull();
  });

  it("does not show what it seals", () => {
    expect(seal({ token: "ghu_secret" }, "s1")).not.toContain("ghu_secret");
  });
});

describe("safeNext", () => {
  it("only returns to a path on this site", () => {
    expect(safeNext("/a/b?x=1")).toBe("/a/b?x=1");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("/\t/evil.example")).toBe("/");
    expect(safeNext("/\n\\evil.example")).toBe("/");
    expect(safeNext("/.//evil.example")).toBe("/");
    expect(safeNext("/a/..//evil.example")).toBe("/");
    expect(safeNext("/runs/a#case")).toBe("/runs/a#case");
    expect(safeNext(null)).toBe("/");
  });
});

describe("signed", () => {
  const body = '{"action":"completed"}';
  const good = "sha256=" + createHmac("sha256", "secret").update(body).digest("hex");
  it("accepts GitHub's signature and nothing else", () => {
    expect(signed("secret", body, good)).toBe(true);
    expect(signed("other", body, good)).toBe(false);
    expect(signed("secret", body + " ", good)).toBe(false);
    expect(signed("secret", body, null)).toBe(false);
    expect(signed("secret", body, "sha256=abc")).toBe(false);
  });
});

describe("appJwt", () => {
  it("is an RS256 JWT for the App, valid ten minutes from a minute back", () => {
    const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
    const pem = privateKey.export({ type: "pkcs1", format: "pem" }).toString();
    const jwt = appJwt("123", pem.replace(/\n/g, "\\n"), 1000);
    const [head, body, sig] = jwt.split(".");
    expect(JSON.parse(Buffer.from(head, "base64url").toString())).toEqual({ alg: "RS256", typ: "JWT" });
    expect(JSON.parse(Buffer.from(body, "base64url").toString())).toEqual({ iat: 940, exp: 1540, iss: "123" });
    expect(createVerify("RSA-SHA256").update(`${head}.${body}`).verify(publicKey, Buffer.from(sig, "base64url"))).toBe(true);
  });
});
