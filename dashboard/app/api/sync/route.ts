import { NextResponse, type NextRequest } from "next/server";
import { currentUser } from "@/lib/auth";
import { userRepos } from "@/lib/github";
import { backfill } from "@/lib/ingest";

export const maxDuration = 300;

/** The "Read runs from GitHub" button of a project page: stores the gate runs GitHub still has for one repository. */
export async function POST(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (origin && origin !== req.nextUrl.origin) return new NextResponse("cross-site request", { status: 403 });
  const user = await currentUser();
  if (!user || user.expires < Date.now()) return NextResponse.redirect(new URL("/api/auth/login", req.nextUrl.origin), 303);
  const name = String((await req.formData()).get("repo") ?? "").toLowerCase();
  const repo = (await userRepos(user.token)).find((r) => r.full_name.toLowerCase() === name);
  if (!repo) return new NextResponse("not found", { status: 404 });
  const stored = await backfill(repo.installation, repo);
  return NextResponse.redirect(new URL(`/${repo.full_name}?read=${stored}`, req.nextUrl.origin), 303);
}
