import type { ReactNode } from "react";
import { slugify } from "@/lib/docs";

/** Things to do in order. Each child is a `Step`. */
export function Steps({ children }: { children: ReactNode }) {
  return <ol role="list" className="steps list-none pl-0">{children}</ol>;
}

/** One step: what to do (`title`, also its anchor) and how. */
export function Step({ title, id, children }: { title: string; id?: string; children: ReactNode }) {
  return (
    <li className="step relative grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-3 pb-6 last:pb-0">
      <span
        aria-hidden
        className="step-number relative z-10 grid size-9 place-items-center rounded-full border border-ink-3 bg-paper font-display text-lg font-extrabold"
      />
      <div className="min-w-0 pt-1 [&>*+*]:mt-3">
        <h3 id={id ?? slugify(title)} className="mt-0">
          {title}
        </h3>
        {children}
      </div>
    </li>
  );
}
