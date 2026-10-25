import { after, type NextRequest } from "next/server";
import { installationToken, signed } from "@/lib/github";
import { backfill, ingestRun } from "@/lib/ingest";
import { env } from "@/lib/session";

export const maxDuration = 300;

type Ref = { id: number; full_name: string };

/** GitHub gives a delivery ten seconds, so this answers first and reads the artifacts after. */
export async function POST(req: NextRequest) {
  const body = await req.text();
  if (!signed(env("GITHUB_WEBHOOK_SECRET"), body, req.headers.get("x-hub-signature-256"))) {
    return new Response("bad signature", { status: 401 });
  }
  const event = req.headers.get("x-github-event");
  const p = JSON.parse(body);
  const installation: number | undefined = p.installation?.id;
  const work = (what: string, job: () => Promise<number>) =>
    after(async () => {
      try {
        console.log(`${what}: stored ${await job()} run(s)`);
      } catch (e) {
        console.error(`${what} failed`, e);
      }
    });
  if (event === "workflow_run" && p.action === "completed" && installation) {
    work(`run ${p.workflow_run.id} of ${p.repository.full_name}`, async () =>
      ingestRun(await installationToken(installation), p.repository, p.workflow_run),
    );
  } else if (installation && ((event === "installation" && p.action === "created") || (event === "installation_repositories" && p.action === "added"))) {
    const repos: Ref[] = p.repositories ?? p.repositories_added ?? [];
    work(`backfill of ${repos.map((r) => r.full_name).join(", ")}`, async () => {
      const token = await installationToken(installation);
      let stored = 0;
      for (const repo of repos) stored += await backfill(installation, repo, token);
      return stored;
    });
  }
  return new Response(null, { status: 202 });
}
