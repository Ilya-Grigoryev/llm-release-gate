import { Fragment, type ReactNode } from "react";
import { LampDot, type Lamp } from "../verdict";

/*
 * The parts the docs' figures are built from. Colour carries meaning only: --base (main) and --cand (the request) for
 * the two versions; --go, --stop, --wait for verdicts; everything else is ink on panel. Text in a figure uses the body
 * face; numbers, ids and code use the code face.
 */

export { LampDot, type Lamp };

/** What a figure's content is: made-up example data, a simulation, a plan, or a real measurement. */
export function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-block rounded-full border border-line bg-paper px-2.5 py-0.5 text-sm leading-5 text-ink-2">
      {children}
    </span>
  );
}

/** A figure's header line: the tag on the left, anything else (a picker, a legend) on the right. */
export function FigureHead({ tag, children }: { tag?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      {tag ? <Tag>{tag}</Tag> : <span />}
      {children}
    </div>
  );
}

/** A colour key: a swatch and its label. */
export function Key({ items }: { items: { color: string; label: string; dashed?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-2.5 w-4 rounded-sm"
            style={i.dashed ? { border: `1.5px dashed ${i.color}` } : { background: i.color }}
          />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** A box in a diagram: a short title and, under it, a line or two of detail. `tone` colours its edge. */
export function Node({
  title,
  children,
  tone = "ink",
  dashed = false,
  className = "",
}: {
  title: ReactNode;
  children?: ReactNode;
  tone?: "ink" | "base" | "cand" | "go" | "stop" | "wait" | "muted";
  dashed?: boolean;
  className?: string;
}) {
  const edge = { ink: "var(--ink-3)", base: "var(--base)", cand: "var(--cand)", go: "var(--go)", stop: "var(--stop)", wait: "var(--wait)", muted: "var(--line)" }[tone];
  return (
    <div
      className={`min-w-0 rounded-md bg-panel px-3 py-2 ${className}`}
      style={{ border: `1.5px ${dashed ? "dashed" : "solid"} ${edge}` }}
    >
      <div className="leading-snug font-bold">{title}</div>
      {children && <div className="mt-0.5 text-sm leading-snug text-ink-2">{children}</div>}
    </div>
  );
}

/** An arrow between diagram boxes: right on wide screens, down when the diagram stacks on a phone. */
export function Arrow({ label, down = false, muted = false }: { label?: ReactNode; down?: boolean; muted?: boolean }) {
  const color = muted ? "var(--line)" : "var(--ink-3)";
  return (
    <div className={`flex items-center justify-center gap-1 text-sm text-ink-2 ${down ? "flex-col py-1" : "flex-col py-1 sm:flex-row sm:px-1 sm:py-0"}`}>
      <svg aria-hidden viewBox="0 0 24 24" className={`size-5 shrink-0 ${down ? "rotate-90" : "rotate-90 sm:rotate-0"}`}>
        <path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label && <span className="text-center leading-tight">{label}</span>}
    </div>
  );
}

/** Inline formatting the gate's comments use: `code`, **bold**, [link](…). */
function inline(text: string): ReactNode {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]*\))/g);
  return parts.map((p, i) => {
    if (p.startsWith("`")) return <code key={i} className="rounded bg-paper px-1 font-mono text-[0.9em]">{p.slice(1, -1)}</code>;
    if (p.startsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    const link = p.match(/^\[([^\]]+)\]/);
    if (link) return <span key={i} className="text-arm-base underline underline-offset-2">{link[1]}</span>;
    return <Fragment key={i}>{p}</Fragment>;
  });
}

/**
 * A comment as the gate posts it on a pull request, drawn like a GitHub comment card. `markdown` is the comment's
 * text in the gate's own format: paragraphs, and a table of cases. `marks` puts numbered markers in the margin of the
 * paragraph (or table) with that index, so a figure can explain the comment part by part.
 */
export function CommentCard({ markdown, marks = {}, compact = false }: { markdown: string; marks?: Record<number, string>; compact?: boolean }) {
  const blocks = markdown.trim().split(/\n\s*\n/);
  return (
    <div className="overflow-hidden rounded-md border border-line bg-panel text-[0.95rem] leading-relaxed">
      <div className="flex items-center gap-2 border-b border-line bg-paper px-3 py-1.5 text-sm text-ink-2">
        <span aria-hidden className="grid size-5 place-items-center rounded-full bg-ink text-[0.6rem] font-bold text-panel">
          G
        </span>
        <span className="font-bold text-ink">github-actions</span> commented
      </div>
      <div className={`space-y-2.5 ${compact ? "px-3 py-2.5" : "px-4 py-3"} ${Object.keys(marks).length ? "pl-10" : ""}`}>
        {blocks.map((block, i) => {
          const mark = marks[i];
          const lines = block.split("\n");
          const body = lines[0].trim().startsWith("|") ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  {lines
                    .filter((l) => !/^\|\s*-/.test(l.trim()))
                    .map((l, r) => (
                      <tr key={r} className={r === 0 ? "font-bold" : "border-t border-line"}>
                        {l
                          .trim()
                          .replace(/^\||\|$/g, "")
                          .split("|")
                          .map((c, k) => (
                            <td key={k} className={`py-1 pr-4 ${k > 0 ? "font-mono tabular-nums" : ""}`}>
                              {inline(c.trim())}
                            </td>
                          ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="min-w-0 [overflow-wrap:anywhere]">
              {lines.map((l, k) => (
                <Fragment key={k}>
                  {k > 0 && <br />}
                  {inline(l)}
                </Fragment>
              ))}
            </p>
          );
          return (
            <div key={i} className="relative">
              {mark && (
                <span
                  aria-label={`Marker ${mark}`}
                  className="absolute top-0.5 -left-7 grid size-5 place-items-center rounded-full bg-ink font-mono text-[0.7rem] font-bold text-panel"
                >
                  {mark}
                </span>
              )}
              {body}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Until a figure is drawn: its title and its text alternative, so the page still says what it shows. */
export function Pending({ title, alt }: { title: string; alt: string }) {
  return (
    <div className="space-y-2">
      <p className="font-bold">{title}</p>
      <p className="text-ink-2">{alt}</p>
    </div>
  );
}
