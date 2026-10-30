import type { ReactNode } from "react";

type Kind = "note" | "planned" | "today";

const LOOK: Record<Kind, { box: string; title?: string }> = {
  note: { box: "border border-line bg-panel" },
  // Dashed: drawn but not built.
  planned: { box: "border border-dashed border-ink-3", title: "Planned, not built yet" },
  today: { box: "border border-line border-l-ink border-l-[3px] bg-panel", title: "Today" },
};

/**
 * A remark beside the text. `note` is an aside; `planned` marks a feature that is designed but not in the gate yet
 * (`when` says when, e.g. "stage C"); `today` says how the gate behaves now, next to a planned change.
 */
export function Callout({ kind = "note", title, when, children }: { kind?: Kind; title?: string; when?: string; children: ReactNode }) {
  const look = LOOK[kind];
  const heading = title ?? (kind === "planned" && when ? `Planned for ${when}` : look.title);
  return (
    <div role="note" className={`rounded-md px-4 py-3 ${look.box}`}>
      {heading && <p className="font-bold">{heading}</p>}
      <div className={`text-ink-2 [&>*+*]:mt-2 ${heading ? "mt-1" : ""}`}>{children}</div>
    </div>
  );
}
