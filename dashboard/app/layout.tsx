import type { Metadata } from "next";
import { Atkinson_Hyperlegible, Bricolage_Grotesque, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { SiteNav } from "@/components/site-nav";
import { currentUser } from "@/lib/auth";
import "./globals.css";

const display = Bricolage_Grotesque({ variable: "--font-display-face", subsets: ["latin"], axes: ["opsz"] });
const body = Atkinson_Hyperlegible({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
});
const code = JetBrains_Mono({ variable: "--font-code", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Release gate", template: "%s | Release gate" },
  description: "llm-release-gate: a CI release gate for LLM apps, and the runs it decided on your pull requests.",
  robots: { index: false, follow: false },
};

async function Account() {
  const user = await currentUser();
  if (!user)
    return (
      <form action="/api/auth/login">
        <button className="text-sm text-ink-2 underline-offset-4 hover:text-ink hover:underline">Sign in</button>
      </form>
    );
  return (
    <div className="flex items-center gap-2 sm:gap-3 text-sm">
      {/* eslint-disable-next-line @next/next/no-img-element -- a 24px avatar from GitHub */}
      <img src={user.avatar} alt="" className="hidden size-6 rounded-full sm:block" />
      <span className="hidden text-ink-2 sm:inline">{user.login}</span>
      <form action="/api/auth/logout" method="post">
        <button className="text-ink-2 underline-offset-4 hover:text-ink hover:underline">Sign out</button>
      </form>
    </div>
  );
}

/** Two tracks under a barrier: the gate's mark. */
function Mark() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
      <path d="M8 3v18" stroke="var(--base)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M16 3v18" stroke="var(--cand)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M3 10.5h18" stroke="var(--ink)" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${code.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <a href="#content" className="sr-only z-50 rounded bg-ink px-3 py-2 text-paper focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
          Skip to content
        </a>
        <header className="sticky top-0 z-30 h-(--header) border-b border-line bg-paper/95 backdrop-blur-sm">
          <div className="flex h-full items-center gap-4 px-4 whitespace-nowrap sm:gap-6 sm:px-6">
            <Link href="/" className="flex shrink-0 items-center gap-2 font-display text-base font-extrabold tracking-tight sm:text-lg">
              <Mark />
              release gate
            </Link>
            <SiteNav />
            <div className="ml-auto">
              <Account />
            </div>
          </div>
        </header>
        <div id="content" className="flex flex-1 flex-col">
          {children}
        </div>
      </body>
    </html>
  );
}
