import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_PATH, access, isDocsPath } from "@/lib/access";
import { SESSION, env, unseal, type Session } from "@/lib/session";

/**
 * The documentation's only gate. A layout cannot be one: the router renders its pages anyway. Visitors who may not read
 * the docs get the sign-in or no-access screen at the same URL. The session cookie is enough to know who it is; an
 * expired GitHub token does not matter here, because the docs never call GitHub.
 */
export function proxy(req: NextRequest) {
  const path = req.nextUrl.pathname;
  if (!isDocsPath(path)) return NextResponse.next();
  const session = unseal<Session>(req.cookies.get(SESSION)?.value ?? "", env("SESSION_SECRET"));
  if (access(session?.login).state === "allowed") return NextResponse.next();
  const url = new URL(ACCESS_PATH, req.nextUrl.origin);
  url.searchParams.set("next", path + req.nextUrl.search);
  return NextResponse.rewrite(url);
}

export const config = { matcher: ["/", "/docs/:path*"] };
