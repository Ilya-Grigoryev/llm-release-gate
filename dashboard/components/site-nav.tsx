"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PAGES } from "@/lib/docs";

/** Docs and Projects in the header; the one the reader is in is marked. The home page belongs to neither. */
export function SiteNav() {
  const path = usePathname();
  const docs = path === "/docs" || path.startsWith("/docs/");
  const projects = !docs && path !== "/";
  const item = (active: boolean) =>
    `relative flex h-full items-center px-0.5 text-base ${
      active ? "text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-ink" : "text-ink-2 hover:text-ink"
    }`;
  return (
    <nav aria-label="Site" className="flex h-full items-center gap-4 sm:gap-5">
      <Link href={PAGES[0].href} className={item(docs)} aria-current={docs ? "true" : undefined}>
        Docs
      </Link>
      <Link href="/projects" className={item(projects)} aria-current={projects ? "true" : undefined}>
        Projects
      </Link>
    </nav>
  );
}
