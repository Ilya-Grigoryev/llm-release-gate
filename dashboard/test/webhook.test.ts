import { createHmac } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

const jobs = vi.hoisted(() => [] as (() => Promise<void>)[]);
const ingest = vi.hoisted(() => ({ ingestRun: vi.fn(), backfill: vi.fn() }));
vi.mock("next/server", async (original) => ({ ...(await original<object>()), after: (job: () => Promise<void>) => jobs.push(job) }));
vi.mock("../lib/ingest", () => ingest);
vi.mock("../lib/github", async (original) => ({ ...(await original<object>()), installationToken: async () => "inst-token" }));

import { POST } from "../app/api/github/webhook/route";

const secret = "hook-secret";
const deliver = (event: string, payload: object, sign = secret) => {
  const body = JSON.stringify(payload);
  const signature = "sha256=" + createHmac("sha256", sign).update(body).digest("hex");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the route reads only text() and headers
  return POST(new Request("https://x/api/github/webhook", { method: "POST", body, headers: { "x-github-event": event, "x-hub-signature-256": signature } }) as any);
};

beforeEach(() => {
  process.env.GITHUB_WEBHOOK_SECRET = secret;
  jobs.length = 0;
  vi.resetAllMocks();
  ingest.ingestRun.mockResolvedValue(1);
  ingest.backfill.mockResolvedValue(2);
});

describe("webhook", () => {
  it("refuses a delivery signed with another secret", async () => {
    expect((await deliver("workflow_run", { action: "completed" }, "other")).status).toBe(401);
    expect(jobs).toHaveLength(0);
  });

  it("answers at once and reads a finished run afterwards", async () => {
    const run = { id: 99 };
    const repository = { id: 7, full_name: "acme/app" };
    const res = await deliver("workflow_run", { action: "completed", installation: { id: 5 }, repository, workflow_run: run });
    expect(res.status).toBe(202);
    expect(ingest.ingestRun).not.toHaveBeenCalled();
    await jobs[0]();
    expect(ingest.ingestRun).toHaveBeenCalledWith("inst-token", repository, run);
  });

  it("reads the repositories an installation adds", async () => {
    const repos = [{ id: 7, full_name: "acme/app" }, { id: 8, full_name: "acme/web" }];
    await deliver("installation_repositories", { action: "added", installation: { id: 5 }, repositories_added: repos });
    await jobs[0]();
    expect(ingest.backfill.mock.calls).toEqual([
      [5, repos[0], "inst-token"],
      [5, repos[1], "inst-token"],
    ]);
  });

  it("ignores other events", async () => {
    expect((await deliver("workflow_run", { action: "requested", installation: { id: 5 } })).status).toBe(202);
    expect((await deliver("ping", { zen: "hi" })).status).toBe(202);
    expect(jobs).toHaveLength(0);
  });
});
