"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { DOCS, PAGES, neighbours } from "@/lib/docs";

const current = (path: string) => path.replace(/\/$/, "");

/** The pages by group, in reading order; the open page is marked. */
export function DocsNav({ onNavigate }: { onNavigate?: () => void }) {
  const path = current(usePathname());
  return (
    <nav aria-label="Documentation">
      {DOCS.map(({ group, pages }) => (
        <div key={group} className="mb-6 last:mb-0">
          <p className="mb-1.5 text-sm font-bold text-ink-2">{group}</p>
          <ul>
            {pages.map((p) => {
              const href = `/docs/${p.slug}`;
              const active = href === path;
              return (
                <li key={p.slug}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`-ml-3 block border-l-2 py-1 pl-3 ${
                      active ? "border-ink font-bold text-ink" : "border-transparent text-ink-2 hover:border-line hover:text-ink"
                    }`}
                  >
                    {p.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** On a phone the sidebar folds behind a button that names the open page. */
export function MobileDocsNav() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const path = current(usePathname());
  const title = PAGES.find((p) => p.href === path)?.title ?? "Overview";

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="sticky top-(--header) z-20 border-b border-line bg-paper/95 backdrop-blur-sm min-[1100px]:hidden">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left sm:px-6"
      >
        <svg viewBox="0 0 16 16" className="size-4 shrink-0" aria-hidden>
          {open ? (
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
          ) : (
            <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
          )}
        </svg>
        <span className="sr-only">{open ? "Close" : "Open"} the documentation menu. Current page: </span>
        <span className="truncate font-bold">{title}</span>
      </button>
      <div id={id} hidden={!open} className="max-h-[calc(100dvh-var(--header)-3.25rem)] overflow-y-auto border-t border-line px-4 py-5 sm:px-6">
        <DocsNav onNavigate={() => setOpen(false)} />
      </div>
    </div>
  );
}

/** Links to the previous and next page in reading order. */
export function Pager() {
  const { prev, next } = neighbours(usePathname());
  if (!prev && !next) return null;
  const link = "group block rounded-md border border-line px-4 py-3 hover:border-ink-3";
  return (
    <nav aria-label="Previous and next page" className="mt-16 grid gap-3 border-t border-line pt-8 sm:grid-cols-2">
      {prev ? (
        <Link href={prev.href} className={link}>
          <span className="block text-sm text-ink-2">Previous</span>
          <span className="font-bold group-hover:underline">{prev.title}</span>
        </Link>
      ) : (
        <span />
      )}
      {next && (
        <Link href={next.href} className={`${link} sm:text-right`}>
          <span className="block text-sm text-ink-2">Next</span>
          <span className="font-bold group-hover:underline">{next.title}</span>
        </Link>
      )}
    </nav>
  );
}
