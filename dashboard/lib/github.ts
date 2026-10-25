import { createHmac, createSign, timingSafeEqual } from "node:crypto";
import { env } from "./session";

const API = "https://api.github.com";

export class GitHubError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function headers(token: string): Record<string, string> {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "llm-release-gate-dashboard",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

export async function gh<T>(path: string, token: string, method = "GET"): Promise<T> {
  const res = await fetch(API + path, { method, headers: headers(token), cache: "no-store" });
  if (!res.ok) throw new GitHubError(res.status, `${method} ${path}: ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

/** The bytes of a workflow artifact. GitHub answers with a redirect to storage that must not get the token. */
export async function download(path: string, token: string): Promise<Uint8Array> {
  const res = await fetch(API + path, { headers: headers(token), redirect: "manual", cache: "no-store" });
  const location = res.headers.get("location");
  if (res.status !== 302 || !location) throw new GitHubError(res.status, `GET ${path}: ${res.status}`);
  const file = await fetch(location, { cache: "no-store" });
  if (!file.ok) throw new GitHubError(file.status, `artifact download: ${file.status}`);
  return new Uint8Array(await file.arrayBuffer());
}

/** The JWT a GitHub App signs to act as itself (RS256, valid ten minutes, a minute back for clock drift). */
export function appJwt(appId: string, privateKey: string, now = Math.floor(Date.now() / 1000)): string {
  const part = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const unsigned = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: appId })}`;
  const signature = createSign("RSA-SHA256").update(unsigned).sign(privateKey.replace(/\\n/g, "\n"));
  return `${unsigned}.${signature.toString("base64url")}`;
}

export async function installationToken(installation: number): Promise<string> {
  const jwt = appJwt(env("GITHUB_APP_ID"), env("GITHUB_APP_PRIVATE_KEY"));
  return (await gh<{ token: string }>(`/app/installations/${installation}/access_tokens`, jwt, "POST")).token;
}

/** Whether a webhook body carries the signature GitHub makes with the App's webhook secret. */
export function signed(secret: string, body: string, signature: string | null): boolean {
  if (!signature?.startsWith("sha256=")) return false;
  const want = Buffer.from(createHmac("sha256", secret).update(body).digest("hex"));
  const got = Buffer.from(signature.slice("sha256=".length));
  return got.length === want.length && timingSafeEqual(got, want);
}

export type Repo = { id: number; full_name: string; private: boolean; html_url: string; installation: number };

/** The repositories where the App is installed and the signed-in user has access: what the user may see here. */
export async function userRepos(token: string): Promise<Repo[]> {
  const { installations } = await gh<{ installations: { id: number }[] }>("/user/installations?per_page=100", token);
  const lists = await Promise.all(
    installations.map(async ({ id }) => {
      const repos: Repo[] = [];
      for (let page = 1; ; page++) {
        const r = await gh<{ total_count: number; repositories: Omit<Repo, "installation">[] }>(
          `/user/installations/${id}/repositories?per_page=100&page=${page}`,
          token,
        );
        repos.push(...r.repositories.map((x) => ({ id: x.id, full_name: x.full_name, private: x.private, html_url: x.html_url, installation: id })));
        if (!r.repositories.length || repos.length >= r.total_count) return repos;
      }
    }),
  );
  return lists.flat().sort((a, b) => a.full_name.localeCompare(b.full_name));
}
