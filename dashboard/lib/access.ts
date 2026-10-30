/**
 * Who may read the documentation: signed-in GitHub users whose login is in DOCS_VIEWERS (comma-separated, any case).
 * Unset or empty means nobody. The dashboard's pages keep their own check (the user's repositories on GitHub).
 */

export type Access = { state: "signed-out" } | { state: "denied"; login: string } | { state: "allowed"; login: string };

/** The logins in a DOCS_VIEWERS value, lowercased; blanks between commas are dropped. */
export function parseViewers(raw: string | undefined): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function canView(login: string | null | undefined, viewers: Set<string>): boolean {
  return !!login && viewers.has(login.trim().toLowerCase());
}

/** What a visitor gets: `login` is the signed-in user's, or null without a session. */
export function access(login: string | null | undefined, raw: string | undefined = process.env.DOCS_VIEWERS): Access {
  if (!login) return { state: "signed-out" };
  return canView(login, parseViewers(raw)) ? { state: "allowed", login } : { state: "denied", login };
}

/** The paths the documentation lives on: /docs and everything under it. The home page is open to everyone. */
export function isDocsPath(pathname: string): boolean {
  return pathname === "/docs" || pathname.startsWith("/docs/");
}

/** Where the proxy shows the sign-in or no-access screen instead of a docs page. */
export const ACCESS_PATH = "/access";
