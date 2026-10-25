import { strToU8, zipSync } from "fflate";
import { beforeEach, describe, expect, it, vi } from "vitest";

const github = vi.hoisted(() => ({ gh: vi.fn(), download: vi.fn(), installationToken: vi.fn() }));
const db = vi.hoisted(() => ({ known: vi.fn(), insertRun: vi.fn() }));
vi.mock("../lib/github", () => github);
vi.mock("../lib/db", () => db);

import { backfill, ingestRun, type WorkflowRun } from "../lib/ingest";

const repo = { id: 7, full_name: "acme/app" };
const run = (attempt: number): WorkflowRun => ({
  id: 99,
  run_attempt: attempt,
  display_title: `attempt ${attempt}`,
  head_branch: "fix",
  head_sha: "abc",
  html_url: "https://github.com/acme/app/actions/runs/99",
  created_at: `2026-10-25T1${attempt}:00:00Z`,
  run_started_at: `2026-10-25T1${attempt}:00:05Z`,
  pull_requests: [{ number: 4 }],
});
const zip = zipSync({
  "verdict.json": strToU8(JSON.stringify({ outcome: "pass", exit_code: 0, base_mean: 1, candidate_mean: 1, diff_pp: 0 })),
  "base.jsonl": strToU8('{"case": "a", "rep": 0, "config_hash": "c", "score": 1}\n'),
  "candidate.jsonl": strToU8('{"case": "a", "rep": 0, "config_hash": "c", "score": 1}\n'),
});

const casesZip = zipSync({ "a.yaml": strToU8("id: a\n") });

beforeEach(() => {
  vi.resetAllMocks();
  github.download.mockImplementation(async (path: string) => (path.includes("/artifacts/6/") ? casesZip : zip));
  db.known.mockResolvedValue(new Set(["3"]));
});

describe("ingestRun", () => {
  it("stores new gate artifacts only, each with its own attempt", async () => {
    github.gh.mockImplementation(async (path: string) => {
      if (path.endsWith("/artifacts?per_page=100"))
        return {
          artifacts: [
            { id: 1, name: "release-gate-2", expired: false },
            { id: 2, name: "release-gate-support-1", expired: false },
            { id: 3, name: "release-gate-3", expired: false },
            { id: 4, name: "release-gate-1", expired: true },
            { id: 5, name: "coverage-2", expired: false },
            { id: 6, name: "release-gate-2-cases", expired: false },
          ],
        };
      if (path.endsWith("/attempts/1")) return run(1);
      throw new Error(`unexpected ${path}`);
    });
    expect(await ingestRun("t", repo, run(2))).toBe(2);
    expect(db.known).toHaveBeenCalledWith([1, 2, 3]);
    const stored = db.insertRun.mock.calls.map(([meta, summary]) => [meta.artifact_id, meta.gate, meta.attempt, meta.title, meta.created_at, summary.outcome]);
    expect(stored).toEqual([
      [1, "", 2, "attempt 2", "2026-10-25T12:00:05Z", "pass"],
      [2, "support", 1, "attempt 1", "2026-10-25T11:00:05Z", "pass"],
    ]);
    expect(db.insertRun.mock.calls[0][0]).toMatchObject({ repo_id: 7, repo: "acme/app", run_id: 99, pr: 4 });
    expect(db.insertRun.mock.calls[0][3]).toEqual({ a: { spec: { id: "a" }, inputs: {} } });
    expect(db.insertRun.mock.calls[1][3]).toBeNull();
    expect(github.download.mock.calls.map(([p]) => p.split("/").at(-2))).toEqual(["1", "6", "2"]);
  });
});

describe("backfill", () => {
  it("reads each run with unstored gate artifacts once", async () => {
    github.installationToken.mockResolvedValue("t");
    github.gh.mockImplementation(async (path: string) => {
      if (path.includes("/actions/artifacts?"))
        return {
          artifacts: [
            { id: 1, name: "release-gate-1", expired: false, workflow_run: { id: 99 } },
            { id: 2, name: "release-gate-x-1", expired: false, workflow_run: { id: 99 } },
            { id: 3, name: "release-gate-1", expired: false, workflow_run: { id: 98 } },
            { id: 6, name: "coverage-1", expired: false, workflow_run: { id: 97 } },
          ],
        };
      if (path.endsWith("/actions/runs/99")) return run(1);
      if (path.endsWith("/runs/99/artifacts?per_page=100")) return { artifacts: [{ id: 1, name: "release-gate-1", expired: false }] };
      throw new Error(`unexpected ${path}`);
    });
    expect(await backfill(5, repo)).toBe(1);
    expect(github.installationToken).toHaveBeenCalledWith(5);
    expect(github.gh.mock.calls.filter(([p]) => p.endsWith("/actions/runs/98"))).toEqual([]);
  });
});
