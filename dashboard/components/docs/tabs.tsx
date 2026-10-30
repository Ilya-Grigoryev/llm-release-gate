"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type TabItem = { label: string; content: ReactNode };

/**
 * Alternatives of which the reader needs one, e.g. the same setup for GitHub Actions and for another CI. `label` names
 * the set for screen readers. Arrow keys move between tabs, Home and End jump to the ends.
 */
export function Tabs({ label, items, initial = 0 }: { label: string; items: TabItem[]; initial?: number }) {
  const [active, setActive] = useState(initial);
  const id = useId();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const select = (i: number) => {
    setActive(i);
    tabs.current[i]?.focus();
  };

  const onKey = (e: KeyboardEvent) => {
    const last = items.length - 1;
    const to = { ArrowRight: active + 1, ArrowLeft: active - 1, Home: 0, End: last }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    select(to < 0 ? last : to > last ? 0 : to);
  };

  return (
    <div>
      <div role="tablist" aria-label={label} onKeyDown={onKey} className="flex overflow-x-auto border-b border-line">
        {items.map((item, i) => (
          <button
            key={item.label}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            id={`${id}-tab-${i}`}
            role="tab"
            type="button"
            aria-selected={i === active}
            aria-controls={`${id}-panel-${i}`}
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            className={`relative shrink-0 px-3 py-2.5 text-base whitespace-nowrap focus-visible:-outline-offset-2 ${
              i === active ? "text-ink after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-ink" : "text-ink-2 hover:text-ink"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      {items.map((item, i) => (
        <div
          key={item.label}
          id={`${id}-panel-${i}`}
          role="tabpanel"
          aria-labelledby={`${id}-tab-${i}`}
          hidden={i !== active}
          tabIndex={0}
          className="pt-4 [&>*+*]:mt-3"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
