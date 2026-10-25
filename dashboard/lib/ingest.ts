import { gateArtifact, parseArtifact, summarize } from "./artifact";
import { insertRun, known } from "./db";
import { download, gh, installationToken } from "./github";

/** The fields of a workflow run this reads, as GitHub sends them in a webhook and in the REST API. */
export type WorkflowRun = {
  id: number;
  run_attempt: number;
  display_title: string | null;
  head_branch: string | null;
  head_sha: string | null;
  html_url: string | null;
  created_at: string;
  run_started_at?: string | null;
  pull_requests?: { number: number }[];
};

type Artifact = { id: number; name: string; expired: boolean; workflow_run?: { id: number } };
type RepoRef = { id: number; full_name: string };

/** Stores every gate artifact of one workflow run that is not stored yet; returns how many it stored. */
export async function ingestRun(token: string, repo: RepoRef, run: WorkflowRun): Promise<number> {
  const { artifacts } = await gh<{ artifacts: Artifact[] }>(`/repos/${repo.full_name}/actions/runs/${run.id}/artifacts?per_page=100`, token);
  const gates = artifacts.filter((a) => gateArtifact(a.name) && !a.expired);
  const seen = await known(gates.map((a) => a.id));
  let stored = 0;
  for (const a of gates.filter((a) => !seen.has(String(a.id)))) {
    const { gate, attempt } = gateArtifact(a.name)!;
    // A re-run keeps the artifacts of earlier attempts; each gets the metadata of its own attempt.
    const at = attempt === run.run_attempt ? run : await gh<WorkflowRun>(`/repos/${repo.full_name}/actions/runs/${run.id}/attempts/${attempt}`, token);
    const parsed = parseArtifact(await download(`/repos/${repo.full_name}/actions/artifacts/${a.id}/zip`, token));
    const meta = {
      artifact_id: a.id,
      repo_id: repo.id,
      repo: repo.full_name,
      gate,
      run_id: run.id,
      attempt,
      pr: at.pull_requests?.[0]?.number ?? null,
      title: at.display_title,
      branch: at.head_branch,
      sha: at.head_sha,
      url: at.html_url,
      created_at: at.run_started_at ?? at.created_at,
    };
    await insertRun(meta, summarize(parsed), parsed);
    stored++;
  }
  return stored;
}

/** Stores the gate runs among the repository's 1,000 newest artifacts (GitHub deletes artifacts after 90 days by default). */
export async function backfill(installation: number, repo: RepoRef, token?: string): Promise<number> {
  token ??= await installationToken(installation);
  const runIds = new Set<number>();
  for (let page = 1; page <= 10; page++) {
    const { artifacts } = await gh<{ artifacts: Artifact[] }>(`/repos/${repo.full_name}/actions/artifacts?per_page=100&page=${page}`, token);
    const gates = artifacts.filter((a) => gateArtifact(a.name) && !a.expired && a.workflow_run);
    const seen = await known(gates.map((a) => a.id));
    gates.filter((a) => !seen.has(String(a.id))).forEach((a) => runIds.add(a.workflow_run!.id));
    if (artifacts.length < 100) break;
  }
  let stored = 0;
  for (const id of runIds) stored += await ingestRun(token, repo, await gh<WorkflowRun>(`/repos/${repo.full_name}/actions/runs/${id}`, token));
  return stored;
}
