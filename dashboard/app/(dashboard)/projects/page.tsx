import type { Metadata } from "next";
import Link from "next/link";
import { Outcome } from "@/components/outcome";
import { currentUser, viewer } from "@/lib/auth";
import { overview } from "@/lib/db";
import { date } from "@/lib/format";
import { env } from "@/lib/session";

const install = () => `https://github.com/apps/${env("GITHUB_APP_SLUG")}/installations/new`;

function Landing() {
  return (
    <section className="mx-auto max-w-2xl py-16">
      <h1 className="text-4xl font-semibold tracking-tight">What the release gate decided, case by case</h1>
      <p className="mt-4 text-lg text-ink-2">
        llm-release-gate runs the old and the new version of your LLM pipeline on each pull request and blocks the merge when
        quality drops. Here you see what it decided, on which cases, and what the model answered on each side.
      </p>
      <form action="/api/auth/login" className="mt-8">
        <input type="hidden" name="next" value="/projects" />
        <button className="rounded-md bg-ink px-4 py-2.5 font-medium text-panel hover:opacity-90">Sign in with GitHub</button>
      </form>
      <ul className="mt-12 grid gap-4 text-sm text-ink-2 sm:grid-cols-3">
        <li>
          <b className="block text-ink">History</b>The verdict of each pull request and how the target branch scored over time.
        </li>
        <li>
          <b className="block text-ink">Cases</b>Which cases changed between the two versions, worst first.
        </li>
        <li>
          <b className="block text-ink">Traces</b>The answer, the tool calls and the checks of every run, side by side.
        </li>
      </ul>
    </section>
  );
}

export const metadata: Metadata = { title: "Projects" };

export default async function Projects() {
  if (!(await currentUser())) return <Landing />;
  const { repos } = await viewer("/projects");
  const stats = await overview(repos.map((r) => r.id));
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-ink-2">Repositories where the App is installed and you have access.</p>
        </div>
        <a href={install()} className="text-sm text-ink-2 underline underline-offset-4 hover:text-ink">
          Add repositories
        </a>
      </div>
      {repos.length === 0 ? (
        <div className="mt-8 rounded-lg border border-dashed border-line bg-panel p-8 text-center text-ink-2">
          No repositories yet. <a href={install()} className="underline underline-offset-4">Install the App</a> on a repository that
          uses the gate action.
        </div>
      ) : (
        <ul className="mt-6 divide-y divide-line overflow-hidden rounded-lg border border-line bg-panel">
          {repos.map((repo) => {
            const s = stats.get(repo.id);
            return (
              <li key={repo.id}>
                <Link href={`/${repo.full_name}`} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 hover:bg-canvas">
                  <span className="font-medium">
                    {repo.full_name}
                    {repo.private && <span className="ml-2 rounded border border-line px-1.5 py-0.5 text-xs font-normal text-ink-3">private</span>}
                  </span>
                  {s ? (
                    <span className="flex items-center gap-4 text-sm text-ink-2">
                      <Outcome value={s.last.outcome} />
                      <span className="hidden sm:inline">{s.last.pr ? `#${s.last.pr}` : s.last.branch}</span>
                      <span className="text-ink-3">{date(s.last.created_at)}</span>
                      <span className="text-ink-3">{s.count} runs</span>
                    </span>
                  ) : (
                    <span className="text-sm text-ink-3">no runs yet</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
