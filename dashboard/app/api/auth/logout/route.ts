import { NextResponse, type NextRequest } from "next/server";
import { SESSION } from "@/lib/session";

export function POST(req: NextRequest) {
  const res = NextResponse.redirect(new URL("/", req.nextUrl.origin), 303);
  res.cookies.delete(SESSION);
  return res;
}
