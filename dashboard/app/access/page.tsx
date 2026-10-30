import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ACCESS_PATH, access } from "@/lib/access";
import { currentUser } from "@/lib/auth";
import { safeNext } from "@/lib/session";

export async function generateMetadata(): Promise<Metadata> {
  return { title: access((await currentUser())?.login).state === "denied" ? "No access" : "Sign in" };
}

const button = "inline-flex items-center rounded-md bg-ink px-4 py-2.5 font-bold text-paper hover:opacity-90";

/**
 * What the proxy shows instead of a docs page to a visitor who may not read it, at the page's own URL: a sign-in
 * screen, or a no-access screen that names the signed-in account.
 */
export default async function Access(props: PageProps<"/access">) {
  const raw = (await props.searchParams).next;
  const wanted = safeNext(typeof raw === "string" ? raw : null);
  const next = wanted.startsWith(ACCESS_PATH) ? "/" : wanted;
  const state = access((await currentUser())?.login);
  if (state.state === "allowed") redirect(next);

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-16 sm:px-6 sm:py-24">
      <div className="max-w-[40rem]">
        {state.state === "signed-out" ? (
          <>
            <h1 className="font-display text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">Sign in to read the docs</h1>
            <p className="mt-5 text-lg text-ink-2">
              Only invited GitHub accounts can read the llm-release-gate docs for now.
            </p>
            <form action="/api/auth/login" className="mt-8">
              <input type="hidden" name="next" value={next} />
              <button className={button}>Sign in with GitHub</button>
            </form>
          </>
        ) : (
          <>
            <h1 className="font-display text-4xl font-extrabold tracking-tight text-balance sm:text-5xl">
              No access for {state.login}
            </h1>
            <p className="mt-5 text-lg text-ink-2">
              Only invited GitHub accounts can read the docs, and {state.login} is not on the list. Ask the gate&apos;s author
              to add it, or sign out and use another account. You can still open your projects.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
              <Link href="/projects" className={button}>
                Open your projects
              </Link>
              <form action="/api/auth/logout" method="post">
                <button className="underline underline-offset-4 hover:text-ink-2">Sign out</button>
              </form>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
