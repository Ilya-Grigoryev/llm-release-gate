import { randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { OAUTH, cookie, env, safeNext, seal } from "@/lib/session";

export function GET(req: NextRequest) {
  const state = randomBytes(16).toString("base64url");
  const url = new URL("https://github.com/login/oauth/authorize");
  url.searchParams.set("client_id", env("GITHUB_CLIENT_ID"));
  url.searchParams.set("redirect_uri", `${req.nextUrl.origin}/api/auth/callback`);
  url.searchParams.set("state", state);
  const res = NextResponse.redirect(url);
  res.cookies.set(OAUTH, seal({ state, next: safeNext(req.nextUrl.searchParams.get("next")) }, env("SESSION_SECRET")), cookie(600));
  return res;
}
