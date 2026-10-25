import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

export function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set`);
  return value;
}

/** `data` as an encrypted, tamper-proof cookie value (AES-256-GCM). */
export function seal(data: unknown, secret: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(secret), iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(data)), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

/** What `seal` sealed, or null for a value that was changed, cut or sealed with another secret. */
export function unseal<T>(value: string, secret: string): T | null {
  try {
    const raw = Buffer.from(value, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key(secret), raw.subarray(0, 12), { authTagLength: 16 });
    decipher.setAuthTag(raw.subarray(12, 28));
    return JSON.parse(Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString());
  } catch {
    return null;
  }
}

function key(secret: string): Buffer {
  return createHash("sha256").update(secret).digest();
}

export const SESSION = "gate_session";
export const OAUTH = "gate_oauth";

export type Session = {
  id: number;
  login: string;
  avatar: string;
  token: string;
  expires: number; // ms; the user token of a GitHub App lives 8 hours
};

export const cookie = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge,
});

const HERE = "https://here.invalid";

/** A path on this site to return to after signing in; anything that resolves elsewhere becomes "/". */
export function safeNext(next: string | null): string {
  if (!next?.startsWith("/")) return "/";
  try {
    const url = new URL(next, HERE);
    return url.origin === HERE ? url.pathname + url.search + url.hash : "/";
  } catch {
    return "/";
  }
}
