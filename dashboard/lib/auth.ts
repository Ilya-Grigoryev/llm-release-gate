import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { GitHubError, userRepos, type Repo } from "./github";
import { SESSION, env, unseal, type Session } from "./session";

export const currentUser = cache(async (): Promise<Session | null> => {
  const value = (await cookies()).get(SESSION)?.value;
  return value ? unseal<Session>(value, env("SESSION_SECRET")) : null;
});

const signIn = (here: string) => redirect(`/api/auth/login?next=${encodeURIComponent(here)}`);

/**
 * The signed-in user and the repositories they may see. Without a session, or once its token expired, it sends the
 * browser through sign-in and back to `here`; GitHub skips the prompt for a user who already authorized the App.
 */
export const viewer = cache(async (here: string): Promise<{ user: Session; repos: Repo[] }> => {
  const user = await currentUser();
  if (!user || user.expires < Date.now() + 60_000) signIn(here);
  try {
    return { user: user!, repos: await userRepos(user!.token) };
  } catch (e) {
    if (e instanceof GitHubError && e.status === 401) signIn(here);
    throw e;
  }
});

export function findRepo(repos: Repo[], owner: string, name: string): Repo | undefined {
  const full = `${owner}/${name}`.toLowerCase();
  return repos.find((r) => r.full_name.toLowerCase() === full);
}
