import { neon } from "@neondatabase/serverless";
import type { Parsed, Rec, Summary, Verdict } from "./artifact";
import { env } from "./session";

const sql = () => neon(env("DATABASE_URL"));

/** A run without its records: what the lists and the chart need. */
export type RunRow = Summary & {
  artifact_id: string;
  repo: string;
  gate: string;
  run_id: string;
  attempt: number;
  pr: number | null;
  title: string | null;
  branch: string | null;
  sha: string | null;
  url: string | null;
  created_at: string;
};

export type RunFull = RunRow & { verdict: Verdict | null; comment: string | null; base: Rec[]; candidate: Rec[] };

const COLUMNS = `artifact_id::text, repo, gate, run_id::text, attempt, pr, title, branch, sha, url, to_json(runs.created_at) #>> '{}' as created_at,
  outcome, exit_code, base_mean, candidate_mean, diff_pp, cost, same_version`;

export async function known(artifactIds: number[]): Promise<Set<string>> {
  if (!artifactIds.length) return new Set();
  const rows = await sql()`select artifact_id::text as id from runs where artifact_id = any(${artifactIds})`;
  return new Set(rows.map((r) => r.id as string));
}

export type Meta = {
  artifact_id: number;
  repo_id: number;
  repo: string;
  gate: string;
  run_id: number;
  attempt: number;
  pr: number | null;
  title: string | null;
  branch: string | null;
  sha: string | null;
  url: string | null;
  created_at: string;
};

export async function insertRun(m: Meta, s: Summary, p: Parsed): Promise<void> {
  await sql()`insert into runs (artifact_id, repo_id, repo, gate, run_id, attempt, pr, title, branch, sha, url, created_at,
      outcome, exit_code, base_mean, candidate_mean, diff_pp, cost, same_version, verdict, comment, base, candidate)
    values (${m.artifact_id}, ${m.repo_id}, ${m.repo}, ${m.gate}, ${m.run_id}, ${m.attempt}, ${m.pr}, ${m.title}, ${m.branch},
      ${m.sha}, ${m.url}, ${m.created_at}, ${s.outcome}, ${s.exit_code}, ${s.base_mean}, ${s.candidate_mean}, ${s.diff_pp},
      ${s.cost}, ${s.same_version}, ${JSON.stringify(p.verdict)}::jsonb, ${p.comment}, ${JSON.stringify(p.base)}::jsonb,
      ${JSON.stringify(p.candidate)}::jsonb)
    on conflict (artifact_id) do nothing`;
}

/** The newest run and the number of runs of each repository. */
export async function overview(repoIds: number[]): Promise<Map<number, { last: RunRow; count: number }>> {
  if (!repoIds.length) return new Map();
  const rows = await sql().query(
    `select distinct on (runs.repo_id) runs.repo_id::float8 as repo_id, count(*) over (partition by repo_id)::int as count, ${COLUMNS}
     from runs where repo_id = any($1) order by runs.repo_id, runs.created_at desc`,
    [repoIds],
  );
  return new Map(rows.map((r) => [r.repo_id as number, { last: r as RunRow, count: r.count as number }]));
}

export async function runsOf(repoId: number): Promise<RunRow[]> {
  return (await sql().query(`select ${COLUMNS} from runs where repo_id = $1 order by runs.created_at desc limit 300`, [repoId])) as RunRow[];
}

export async function runOf(repoId: number, artifactId: string): Promise<RunFull | null> {
  if (!/^\d+$/.test(artifactId)) return null;
  const rows = await sql().query(
    `select ${COLUMNS}, verdict, comment, base, candidate from runs where repo_id = $1 and artifact_id = $2`,
    [repoId, artifactId],
  );
  return (rows[0] as RunFull) ?? null;
}
