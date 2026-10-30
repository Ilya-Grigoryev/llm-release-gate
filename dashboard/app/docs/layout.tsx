import { DocsNav, MobileDocsNav, Pager } from "@/components/docs/nav";
import { OnThisPage } from "@/components/docs/toc";
import { ARTICLE_ID } from "@/lib/docs";

/** Sidebar, page and "On this page" from 1100px; a menu button above the page below that. */
export default function DocsLayout({ children }: LayoutProps<"/docs">) {
  return (
    <div className="flex flex-1 flex-col min-[1100px]:grid min-[1100px]:grid-cols-[15rem_minmax(0,1fr)]">
      <MobileDocsNav />
      <aside className="hidden border-r border-line bg-panel min-[1100px]:block">
        <div className="sticky top-(--header) max-h-[calc(100dvh-var(--header))] overflow-y-auto px-6 py-10">
          <DocsNav />
        </div>
      </aside>
      <div className="mx-auto grid w-full max-w-[74rem] flex-1 gap-x-12 px-4 sm:px-6 lg:px-10 min-[1100px]:grid-cols-[minmax(0,1fr)_12rem]">
        <main className="min-w-0 pt-8 pb-16 sm:pt-12">
          <article id={ARTICLE_ID}>{children}</article>
          <Pager />
        </main>
        <div className="hidden min-[1100px]:block">
          <div className="sticky top-(--header) pt-12">
            <OnThisPage />
          </div>
        </div>
      </div>
    </div>
  );
}
