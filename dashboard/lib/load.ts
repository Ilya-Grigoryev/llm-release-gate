import { notFound } from "next/navigation";
import { findRepo, viewer } from "./auth";
import { runOf } from "./db";

/** The run behind a page, after checking that the signed-in user may see its repository. */
export async function loadRun(owner: string, name: string, id: string, here: string) {
  const { repos } = await viewer(here);
  const repo = findRepo(repos, owner, name);
  const run = repo && (await runOf(repo.id, id));
  if (!repo || !run) notFound();
  return { repo, run };
}
