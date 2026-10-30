/** The documentation's pages in reading order, grouped as the sidebar shows them. */
export const DOCS = [
  { group: "Get started", pages: [{ slug: "start", title: "Get started" }] },
  {
    group: "Concepts",
    pages: [
      { slug: "how-it-works", title: "How it works" },
      { slug: "how-it-decides", title: "How it decides" },
      { slug: "what-it-catches", title: "What it catches" },
      { slug: "limits", title: "Limits and comparison" },
      { slug: "method", title: "Method" },
    ],
  },
  {
    group: "Guides",
    pages: [
      { slug: "write-tests", title: "Write tests" },
      { slug: "connect", title: "Connect your app" },
      { slug: "read-a-verdict", title: "Read a verdict" },
      { slug: "dashboard", title: "Dashboard" },
    ],
  },
  { group: "Reference", pages: [{ slug: "reference", title: "Reference" }] },
] as const;

export type DocSlug = (typeof DOCS)[number]["pages"][number]["slug"];
export type DocPage = { slug: DocSlug; title: string; href: string; group: string };

export const PAGES: DocPage[] = DOCS.flatMap(({ group, pages }) => pages.map((p) => ({ ...p, group, href: `/docs/${p.slug}` })));

export function page(slug: DocSlug): DocPage {
  return PAGES.find((p) => p.slug === slug)!;
}

/** The pages before and after the one at `pathname`, in reading order. */
export function neighbours(pathname: string): { prev?: DocPage; next?: DocPage } {
  const i = PAGES.findIndex((p) => p.href === pathname.replace(/\/$/, ""));
  return i < 0 ? {} : { prev: PAGES[i - 1], next: PAGES[i + 1] };
}

/** The element that holds a docs page's text; the table of contents reads its h2 headings. */
export const ARTICLE_ID = "doc-article";

/** An id for a heading: its words, lowercased and joined with hyphens. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`'’"]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
