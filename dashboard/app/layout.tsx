import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { currentUser } from "@/lib/auth";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Release gate", template: "%s · Release gate" },
  description: "The runs of llm-release-gate on your pull requests: verdicts, cases, answers and traces.",
};

async function Account() {
  const user = await currentUser();
  if (!user) return null;
  return (
    <div className="flex items-center gap-3 text-sm">
      {/* eslint-disable-next-line @next/next/no-img-element -- a 24px avatar from GitHub */}
      <img src={user.avatar} alt="" className="size-6 rounded-full" />
      <span className="text-ink-2">{user.login}</span>
      <form action="/api/auth/logout" method="post">
        <button className="text-ink-3 hover:text-ink">Sign out</button>
      </form>
    </div>
  );
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span aria-hidden className="grid size-6 place-items-center rounded bg-ink text-xs text-panel">
                ▲▼
              </span>
              release gate
            </Link>
            <Account />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
