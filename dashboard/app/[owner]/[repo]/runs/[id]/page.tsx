import type { Metadata } from "next";
import Link from "next/link";
import { Crumbs } from "@/components/crumbs";
import { Json } from "@/components/json";
import { Hit, Outcome } from "@/components/outcome";
import { compareCases, share } from "@/lib/artifact";
import { date, points, score, short, usd } from "@/lib/format";
import { loadRun } from "@/lib/load";

export const metadata: Metadata = { title: "Run" };

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="mt-0.5 tabular-nums">{children}</dd>
    </div>
  );
}

export default async function Run(props: PageProps<"/[owner]/[repo]/runs/[id]">) {
  const { owner, repo: name, id } = await props.params;
  const { repo, run } = await loadRun(owner, name, id, `/${owner}/${name}/runs/${id}`);
  const v = run.verdict;
  const rows = compareCases(run.base, run.candidate);
  const changed = rows.filter((r) => r.changed).length;
  const title = run.pr ? `#${run.pr}` : (run.branch ?? "run");
  const scorers = new Set([...run.base, ...run.candidate].map((r) => r.scorer_version).filter(Boolean));
  const rescored = v?.scorer_version && [...scorers].some((s) => s !== v.scorer_version);
  const reps = Math.max(v?.runs_per_case?.base ?? 1, v?.runs_per_case?.candidate ?? 1);

  return (
    <section>
      <Crumbs items={[{ href: "/", label: "Projects" }, { href: `/${repo.full_name}`, label: repo.full_name }, { label: title }]} />
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          {title} <span className="font-normal text-ink-2">{run.title}</span>
        </h1>
        <div className="flex gap-4 text-sm text-ink-2">
          {run.pr && (
            <a href={`${repo.html_url}/pull/${run.pr}`} className="underline underline-offset-4 hover:text-ink">
              pull request
            </a>
          )}
          {run.url && (
            <a href={run.url} className="underline underline-offset-4 hover:text-ink">
              workflow run
            </a>
          )}
        </div>
      </div>
      <p className="mt-1 text-sm text-ink-3">
        {run.branch} · {short(run.sha)} · {date(run.created_at)}
        {run.gate && ` · gate ${run.gate}`}
        {run.attempt > 1 && ` · attempt ${run.attempt}`}
      </p>

      <div className="mt-6 rounded-lg border border-line bg-panel p-5">
        <div className="text-lg font-medium">
          <Outcome value={run.outcome} />
        </div>
        {v ? (
          <>
            <p className="mt-2 text-sm text-ink-2">{v.rule}</p>
            <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
              <Fact label="Mean score, base → candidate">
                {score(v.base_mean)} → {score(v.candidate_mean)}
              </Fact>
              <Fact label="Difference, points">
                <span className={v.diff_pp < 0 ? "text-bad" : ""}>{points(v.diff_pp)}</span>
                {v.limit_pp != null && <span className="text-ink-3"> (blocks below −{v.limit_pp.toFixed(1)})</span>}
              </Fact>
              <Fact label="Cases × runs per version">
                {v.cases} × {v.runs_per_case?.candidate ?? 1}
              </Fact>
              <Fact label="Cost, base + candidate">
                {usd(v.cost_usd?.base)} + {usd(v.cost_usd?.candidate)}
              </Fact>
              <Fact label="Version, base → candidate">
                <span className="font-mono text-xs">
                  {short(v.base_config)} → {short(v.candidate_config)}
                </span>
              </Fact>
              <Fact label="Test set">
                <span className="font-mono text-xs">{short(v.set_hash)}</span>
              </Fact>
            </dl>
            {run.same_version && (
              <p className="mt-4 rounded-md bg-canvas px-3 py-2 text-sm text-ink-2">
                Both sides run the same version. Any difference between them is run-to-run noise of the model, not an effect of
                the pull request.
              </p>
            )}
            {!!v.models_without_date?.length && (
              <p className="mt-3 text-sm text-ink-2">Models without a dated snapshot: {v.models_without_date.join(", ")}.</p>
            )}
          </>
        ) : (
          run.comment && (
            <div className="mt-3">
              <Json value={run.comment} />
            </div>
          )
        )}
      </div>

      <h2 className="mt-8 text-lg font-semibold tracking-tight">Cases</h2>
      <p className="mt-1 text-sm text-ink-2">
        {changed} of {rows.length} changed between the versions; they come first, the most worsened at the top.
        {reps > 1 && ` Scores average the ${reps} runs of a case; the verdict compares the first run of each.`}
      </p>
      {rescored && (
        <p className="mt-2 rounded-md bg-canvas px-3 py-2 text-sm text-ink-2">
          The scores below are the ones each side&apos;s runner recorded ({[...scorers].join(", ")}). The gate scored both sides
          again with {v?.scorer_version}, so its verdict may differ from this table.
        </p>
      )}
      <div className="mt-3 overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-ink-3">
            <tr>
              <th className="px-4 py-2.5 font-normal">Case</th>
              <th className="px-4 py-2.5 text-right font-normal">Base</th>
              <th className="px-4 py-2.5 text-right font-normal">Candidate</th>
              <th className="px-4 py-2.5 font-normal">Checks that changed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => {
              const worse = (r.candidateMean ?? 0) < (r.baseMean ?? 0);
              const errors = [...r.base, ...r.candidate].filter((x) => x.error).length;
              return (
                <tr key={r.case} className={r.changed ? (worse ? "bg-tint-bad/50" : "") : "text-ink-3"}>
                  <td className="max-w-96 px-4 py-2.5">
                    <Link href={`/${repo.full_name}/runs/${run.artifact_id}/${encodeURIComponent(r.case)}`} className="block truncate font-mono text-xs hover:underline">
                      {r.case}
                    </Link>
                    {errors > 0 && <span className="text-xs text-bad">{errors} run(s) with an error</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{score(r.baseMean)}</td>
                  <td className={`px-4 py-2.5 text-right tabular-nums ${worse ? "font-medium text-bad" : ""}`}>{score(r.candidateMean)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                      {r.flipped.map((check) => (
                        <span key={check} className="inline-flex items-center gap-1 font-mono">
                          {check} <Hit value={share(r.base, check)} />→<Hit value={share(r.candidate, check)} />
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
