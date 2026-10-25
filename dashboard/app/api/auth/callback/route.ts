import { NextResponse, type NextRequest } from "next/server";
import { gh } from "@/lib/github";
import { OAUTH, SESSION, cookie, env, safeNext, seal, unseal, type Session } from "@/lib/session";

export async function GET(req: NextRequest) {
  const secret = env("SESSION_SECRET");
  const pending = unseal<{ state: string; next: string }>(req.cookies.get(OAUTH)?.value ?? "", secret);
  const code = req.nextUrl.searchParams.get("code");
  if (req.nextUrl.searchParams.get("error")) {
    const res = new NextResponse("Sign-in was cancelled on GitHub.", { status: 400 });
    res.cookies.delete(OAUTH);
    return res;
  }
  if (!pending || !code || req.nextUrl.searchParams.get("state") !== pending.state) {
    return new NextResponse("Sign-in expired or came from another tab. Go back and sign in again.", { status: 400 });
  }
  const res = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env("GITHUB_CLIENT_ID"),
      client_secret: env("GITHUB_CLIENT_SECRET"),
      code,
      redirect_uri: `${req.nextUrl.origin}/api/auth/callback`,
    }),
  });
  const token = (await res.json()) as { access_token?: string; expires_in?: number; error_description?: string };
  if (!token.access_token) return new NextResponse(`GitHub refused the sign-in: ${token.error_description ?? res.status}`, { status: 400 });
  const user = await gh<{ id: number; login: string; avatar_url: string }>("/user", token.access_token);
  const session: Session = {
    id: user.id,
    login: user.login,
    avatar: user.avatar_url,
    token: token.access_token,
    expires: Date.now() + (token.expires_in ?? 30 * 86400) * 1000,
  };
  const out = NextResponse.redirect(new URL(safeNext(pending.next), req.nextUrl.origin));
  out.cookies.set(SESSION, seal(session, secret), cookie(30 * 86400));
  out.cookies.delete(OAUTH);
  return out;
}
