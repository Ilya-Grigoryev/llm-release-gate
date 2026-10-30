"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ARTICLE_ID } from "@/lib/docs";

type Item = { id: string; text: string };

/** The page's sections (its h2 headings with ids); the one being read is marked. */
export function OnThisPage() {
  const path = usePathname();
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const headings = () => [...document.querySelectorAll<HTMLElement>(`#${ARTICLE_ID} h2[id]`)];
    let frame = requestAnimationFrame(() => {
      setItems(headings().map((h) => ({ id: h.id, text: h.textContent ?? "" })));
      mark();
    });
    // The section being read: the last heading above a line a quarter down the window.
    function mark() {
      const line = window.innerHeight / 4;
      const above = headings().filter((h) => h.getBoundingClientRect().top <= line);
      setActive(above.at(-1)?.id ?? null);
    }
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(mark);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
    };
  }, [path]);

  if (items.length === 0) return null;
  return (
    <nav aria-labelledby="on-this-page" className="text-sm">
      <p id="on-this-page" className="mb-2 font-bold text-ink-2">
        On this page
      </p>
      <ul className="space-y-1.5 border-l border-line">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              aria-current={item.id === active ? "location" : undefined}
              className={`-ml-px block border-l-2 pl-3 ${item.id === active ? "border-ink text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
