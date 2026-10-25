import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Crumbs, Tile } from "@/components/crumbs";
import { Outcome, blocks } from "@/components/outcome";
import { RunsChart, type Point } from "@/components/runs-chart";
import { findRepo, viewer } from "@/lib/auth";
import { runsOf, type RunRow } from "@/lib/db";
import { date, points, score, usd } from "@/lib/format";

export async function generateMetadata(props: PageProps<"/[owner]/[repo]">): Promise<Metadata> {
  const { owner, repo } = await props.params;
  return { title: `${owner}/${repo}` };
}

const runLabel = (r: RunRow) => (r.pr ? `#${r.pr}` : (r.branch ?? "run")) + (r.gate ? ` · ${r.gate}` : "");

export default async function Project(props: PageProps<"/[owner]/[repo]">) {
  const { owner, repo: name } = await props.params;
  const read = (await props.searchParams).read;
  const { repos } = await viewer(`/${owner}/${name}`);
  const repo = findRepo(repos, owner, name);
  if (!repo) notFound();
  const runs = await runsOf(repo.id);
  const decided = runs.filter((r) => r.base_mean != null && r.candidate_mean != null);
  const same = decided.filter((r) => r.same_version);
  const noisy = same.filter((r) => r.diff_pp !== 0);
  const blocked = runs.filter((r) => blocks(r.outcome)).length;
  const cost = runs.reduce((sum, r) => sum + (r.cost ?? 0), 0);
  const chart: Point[] = [...decided].reverse().map((r) => ({
    href: `/${repo.full_name}/runs/${r.artifact_id}`,
    label: runLabel(r),
    title: r.title,
    when: date(r.created_at),
    outcome: r.outcome,
    base: r.base_mean!,
    candidate: r.candidate_mean!,
    same: r.same_version,
  }));

  return (
    <section>
      <Crumbs items={[{ href: "/", label: "Projects" }, { label: repo.full_name }]} />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">
          <a href={repo.html_url} className="hover:underline">
            {repo.full_name}
          </a>
        </h1>
        <form action="/api/sync" method="post" className="flex items-center gap-3">
          {read !== undefined && <span className="text-sm text-ink-3">{read === "0" ? "Nothing new on GitHub." : `Read ${read} new run(s).`}</span>}
          <input type="hidden" name="repo" value={repo.full_name} />
          <button className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm hover:bg-canvas">Read runs from GitHub</button>
        </form>
      </div>

      {runs.length === 0 ? (
        <div className="mt-8 rounded-lg border border-dashed border-line bg-panel p-8 text-ink-2">
          No gate runs stored yet. They arrive when a pull request&apos;s workflow finishes; runs GitHub still keeps (90 days by
          default) come in with <b>Read runs from GitHub</b>.
        </div>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Runs" value={String(runs.length)} note={`${decided.length} with a verdict`} />
            <Tile label="Blocked" value={String(blocked)} note={`quality or budget fail; ${runs.filter((r) => r.outcome === "inconclusive").length} inconclusive`} />
            <Tile
              label="Same version, different score"
              value={`${noisy.length} of ${same.length}`}
              note={same.length ? "runs where only noise could differ" : "no same-version runs yet"}
            />
            <Tile label="Cost of the decisions" value={usd(cost)} note="both versions, list prices" />
          </div>

          {chart.length > 0 && (
            <div className="mt-6 rounded-lg border border-line bg-panel p-4">
              <RunsChart points={chart} />
            </div>
          )}

          <div className="mt-6 overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-ink-3">
                <tr>
                  <th className="px-4 py-2.5 font-normal">Pull request</th>
                  <th className="px-4 py-2.5 font-normal">Verdict</th>
                  <th className="px-4 py-2.5 text-right font-normal">Base → candidate</th>
                  <th className="px-4 py-2.5 text-right font-normal">Points</th>
                  <th className="px-4 py-2.5 text-right font-normal">Cost</th>
                  <th className="px-4 py-2.5 font-normal">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.map((r) => (
                  <tr key={r.artifact_id} className="hover:bg-canvas">
                    <td className="max-w-80 px-4 py-2.5">
                      <Link href={`/${repo.full_name}/runs/${r.artifact_id}`} className="block truncate hover:underline">
                        <span className="font-medium">{runLabel(r)}</span> <span className="text-ink-2">{r.title}</span>
                      </Link>
                      {r.same_version && <span className="text-xs text-ink-3">same version on both sides</span>}
                      {r.attempt > 1 && <span className="ml-2 text-xs text-ink-3">attempt {r.attempt}</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <Outcome value={r.outcome} />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {score(r.base_mean)} → {score(r.candidate_mean)}
                    </td>
                    <td className={`px-4 py-2.5 text-right tabular-nums ${r.diff_pp != null && r.diff_pp < 0 ? "text-bad" : ""}`}>{points(r.diff_pp)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink-2">{usd(r.cost)}</td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-ink-3">{date(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
