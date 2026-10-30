import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CasePanel } from "@/components/case";
import { Crumbs } from "@/components/crumbs";
import { Fold, Json } from "@/components/json";
import { Hit } from "@/components/outcome";
import { Steps } from "@/components/trace";
import { compareCases, type Rec } from "@/lib/artifact";
import { score, seconds } from "@/lib/format";
import { loadRun } from "@/lib/load";

export const metadata: Metadata = { title: "Case" };

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function Answer({ rec, expected }: { rec: Rec; expected?: Record<string, unknown> }) {
  const out = rec.output;
  if (out && typeof out === "object" && !Array.isArray(out)) {
    const o = out as Record<string, unknown>;
    if (typeof o.reply === "string") return <p className="rounded-md bg-canvas p-3 text-sm whitespace-pre-wrap">{o.reply}</p>;
    const fields = Object.entries(o).filter(([, value]) => value === null || typeof value !== "object");
    if (fields.length)
      return (
        <dl className="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1 rounded-md bg-canvas p-3 text-sm">
          {fields.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-ink-3">{key}</dt>
              <dd className="break-words">
                {value == null ? "—" : String(value)}
                {rec.hits?.[key] === false && expected && Object.hasOwn(expected, key) && (
                  <span className="block text-xs text-ink-3">expected {String(expected[key])}</span>
                )}
              </dd>
              <dd>{rec.hits && key in rec.hits ? <Hit value={rec.hits[key]} /> : null}</dd>
            </div>
          ))}
        </dl>
      );
  }
  return <Json value={out ?? rec.raw ?? null} />;
}

function Side({ title, color, recs, flipped, expected }: { title: string; color: string; recs: Rec[]; flipped: Set<string>; expected?: Record<string, unknown> }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-panel p-4">
      <h2 className="flex items-center gap-2 font-medium">
        <span className="size-2.5 rounded-full" style={{ background: color }} />
        {title}
      </h2>
      {recs.length === 0 && <p className="mt-3 text-sm text-ink-3">This case did not run on this side.</p>}
      {recs.map((rec) => (
        <article key={rec.rep} className="mt-4 space-y-4">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-ink-2">
            {recs.length > 1 && <span className="text-ink-3">run {rec.rep + 1}</span>}
            <span>
              score <b className="text-lg text-ink tabular-nums">{score(rec.score)}</b>
            </span>
            {rec.model && <span>{rec.model}</span>}
            {rec.input_tokens != null && (
              <span>
                {rec.input_tokens} → {rec.output_tokens} tokens
              </span>
            )}
            <span>{seconds(rec.latency_s)}</span>
            {!!rec.retries && <span>{rec.retries} retries</span>}
          </div>
          {rec.error != null && (
            <div className="rounded-md bg-tint-bad p-3 text-sm text-bad">
              <Json value={rec.error} />
            </div>
          )}
          <div>
            <h3 className="mb-1.5 text-xs text-ink-3">Answer</h3>
            <Answer rec={rec} expected={expected} />
          </div>
          {rec.hits && (
            <div>
              <h3 className="mb-1.5 text-xs text-ink-3">Checks</h3>
              <ul className="grid gap-1 text-sm">
                {Object.entries(rec.hits).map(([check, value]) => (
                  <li key={check} className={`flex items-center gap-2 font-mono text-xs ${flipped.has(check) ? "font-semibold" : "text-ink-2"}`}>
                    <Hit value={value} /> {check}
                    {flipped.has(check) && <span className="font-sans font-normal text-ink-3">differs</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {rec.trace?.steps?.length ? (
            <div>
              <h3 className="mb-2 text-xs text-ink-3">Steps</h3>
              <Steps steps={rec.trace.steps} last={rec.trace.last_attempt} />
            </div>
          ) : null}
          <div className="space-y-1.5">
            {rec.trace?.state_change != null && <Fold title="state change" value={rec.trace.state_change} />}
            {rec.trace?.final_state != null && <Fold title="final state" value={rec.trace.final_state} />}
            <Fold title="output as recorded" value={rec.output ?? null} />
          </div>
        </article>
      ))}
    </div>
  );
}

export default async function Case(props: PageProps<"/[owner]/[repo]/runs/[id]/[case]">) {
  const { owner, repo: name, id, case: raw } = await props.params;
  const { repo, run } = await loadRun(owner, name, id, `/${owner}/${name}/runs/${id}/${raw}`, true);
  const row = compareCases(run.base, run.candidate).find((r) => r.case === raw || r.case === decode(raw));
  if (!row) notFound();
  const flipped = new Set(row.flipped);
  const file = run.cases?.[row.case];
  const expected = file?.spec.expected as Record<string, unknown> | undefined;
  const title = run.pr ? `#${run.pr}` : (run.branch ?? "run");

  return (
    <section>
      <Crumbs
        items={[
          { href: "/projects", label: "Projects" },
          { href: `/${repo.full_name}`, label: repo.full_name },
          { href: `/${repo.full_name}/runs/${run.artifact_id}`, label: title },
          { label: row.case },
        ]}
      />
      <h1 className="font-mono text-xl font-semibold tracking-tight break-all">{row.case}</h1>
      <p className="mt-1 text-sm text-ink-2">
        Score {score(row.baseMean)} → {score(row.candidateMean)}
        {row.flipped.length > 0 && ` · checks that differ: ${row.flipped.join(", ")}`}
      </p>
      {file ? (
        <CasePanel file={file} />
      ) : (
        <p className="mt-4 text-sm text-ink-3">
          This run&apos;s artifact has no case files, so the input and the expected answer are not shown. The gate keeps them
          from v0.1.0-dev.4 on.
        </p>
      )}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Side title="Base · target branch" color="var(--base)" recs={row.base} flipped={flipped} expected={expected} />
        <Side title="Candidate · pull request" color="var(--cand)" recs={row.candidate} flipped={flipped} expected={expected} />
      </div>
    </section>
  );
}
