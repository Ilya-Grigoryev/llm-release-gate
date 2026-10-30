import type { ReactNode } from "react";
import { Arrow, FigureHead, Node } from "./kit";

/*
 * Wide (@3xl): runner on the left, the program in the middle, answer and checks on the right. Narrow: one column.
 */

function Head({ className = "", small = false }: { className?: string; small?: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={`shrink-0 ${small ? "size-4" : "size-5"} ${className}`}>
      <path
        d="M3 12h16M13 6l6 6-6 6"
        fill="none"
        stroke="var(--ink-3)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** An arrow; `wide` ones exist only in the wide layout, `narrow` ones only when stacked. */
function Edge({ className = "" }: { className?: string }) {
  return (
    <div className={`items-center ${className}`}>
      <Head className="rotate-90 @3xl:rotate-0" />
    </div>
  );
}
const wide = "hidden @3xl:flex @3xl:flex-col @3xl:justify-center @3xl:px-1";
const narrow = "flex py-1 pl-3 @3xl:hidden";

/** Cards stacked behind `children`: many cases, or a process per run. */
function Stack({ children }: { children: ReactNode }) {
  return (
    <span className="relative inline-block">
      <span aria-hidden className="absolute inset-0 translate-x-1.5 translate-y-1.5 rounded border border-ink-3 bg-panel" />
      <span aria-hidden className="absolute inset-0 translate-x-[3px] translate-y-[3px] rounded border border-ink-3 bg-panel" />
      <span className="relative block rounded border border-ink-3 bg-panel px-2 py-1 text-center">{children}</span>
    </span>
  );
}

const C = ({ children }: { children: ReactNode }) => <span className="font-mono text-[0.9em] text-ink">{children}</span>;

const In = ({ children, out = false }: { children: ReactNode; out?: boolean }) => (
  <span className="flex items-center gap-1">
    {!out && <Head small />}
    <span>{children}</span>
    {out && <Head small />}
  </span>
);

export default function Connect1({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="Example" />
      <div className="grid gap-y-2 @3xl:grid-cols-[minmax(0,0.8fr)_auto_minmax(0,2.4fr)_auto_minmax(0,0.85fr)]">
        <Node title="The gate's runner" className="@3xl:self-center">
          <span className="mt-2 mb-1.5 block">
            <Stack>cases</Stack>
          </span>
        </Node>
        <Edge className={narrow} />
        <Edge className={wide} />
        <Node title="Your program">
          any language, a new process per run
          <span className="mt-2 grid gap-2 @lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] @lg:items-center">
            <In>request (JSON, stdin)</In>
            <span className="justify-self-start @lg:justify-self-center">
              <Stack>
                <span className="block">
                  <C>python gate/booking.py</C>
                </span>
                <span className="block">
                  <C>node chat/gate.js</C>
                </span>
              </Stack>
            </span>
            <span className="space-y-1 pt-1 @lg:pt-0">
              <In out>answer (JSON, stdout)</In>
              <In out>exit code</In>
            </span>
          </span>
          <span className="mt-2 block">The answer can carry the run&apos;s steps: model calls, tool calls, the end state.</span>
        </Node>
        <Edge className={wide} />
        <Edge className={narrow} />
        <div className="flex flex-col @3xl:self-center">
          <Node title="Answer + trace">trace optional</Node>
          <Arrow down />
          <Node title="Checks" />
        </div>
      </div>
    </div>
  );
}
