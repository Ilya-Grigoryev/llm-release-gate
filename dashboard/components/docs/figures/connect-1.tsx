import type { ReactNode } from "react";
import { Arrow, FigureHead, Node } from "./kit";

/*
 * Wide (@3xl): runner on the left, three lanes in the middle, answer and checks on the right; each lane has its own
 * arrows. Narrow: one column, one arrow into the lanes and one out of them.
 */

function Head({ className = "", dashed = false, small = false }: { className?: string; dashed?: boolean; small?: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={`shrink-0 ${small ? "size-4" : "size-5"} ${className}`}>
      <path
        d="M3 12h16M13 6l6 6-6 6"
        fill="none"
        stroke="var(--ink-3)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray={dashed ? "3 3" : undefined}
      />
    </svg>
  );
}

/** An arrow and its label; `wide` arrows exist only in the wide layout, `narrow` ones only when stacked. */
function Edge({ children, className = "", dashed = false }: { children?: ReactNode; className?: string; dashed?: boolean }) {
  return (
    <div className={`items-center gap-1 text-sm leading-tight text-ink-2 ${className}`}>
      <Head dashed={dashed} className="rotate-90 @3xl:rotate-0" />
      {children}
    </div>
  );
}
const wide = "hidden @3xl:flex @3xl:flex-col @3xl:justify-center @3xl:px-1";
const narrow = "flex py-1 pl-3 @3xl:hidden";

/** Cards stacked behind `children`: many cases, or one process per run. */
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

const Wrapped = ({ children }: { children: ReactNode }) => (
  <span className="inline-flex items-center gap-1.5 rounded border border-line px-1.5 py-0.5 text-ink">
    {children}
    <span className="rounded-full border border-ink-3 px-1.5 text-xs leading-4 text-ink-2">wrapped</span>
  </span>
);

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
      <div className="grid gap-y-2 @3xl:grid-cols-[minmax(0,0.8fr)_auto_minmax(0,2.4fr)_auto_minmax(0,0.85fr)] @3xl:gap-y-3">
        <Node title="The gate's runner" className="@3xl:col-start-1 @3xl:row-[1/4] @3xl:self-center">
          <span className="mt-2 mb-1.5 block">
            <Stack>cases</Stack>
          </span>
        </Node>
        <Edge className={narrow}>one of two ways</Edge>

        <Edge className={`${wide} @3xl:col-start-2 @3xl:row-start-1`}>
          <span className="flex flex-col items-center">
            <Head className="rotate-180" />
            steps
          </span>
        </Edge>
        <Node title="Python adapter" className="@3xl:col-start-3 @3xl:row-start-1">
          the booking assistant, inside the runner&apos;s process
          <span className="mt-2 block space-y-2 rounded border border-ink-3 p-2">
            <span className="block">
              <C>build(config)</C> once, then <C>run(case)</C> for each case
            </span>
            <span className="flex flex-wrap gap-1.5">
              <Wrapped>OpenAI client</Wrapped>
              <Wrapped>tool function</Wrapped>
            </span>
            <span className="block">The wrappers send each step back to the runner.</span>
          </span>
        </Node>
        <Edge className={`${wide} @3xl:col-start-4 @3xl:row-start-1`} />

        <Edge className={`${wide} @3xl:col-start-2 @3xl:row-start-2`} />
        <Node title="Any program" className="@3xl:col-start-3 @3xl:row-start-2">
          the support chat, a new process per run
          <span className="mt-2 grid gap-2 @lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] @lg:items-center">
            <In>request (JSON, stdin)</In>
            <span className="justify-self-start @lg:justify-self-center">
              <Stack>
                <C>node chat/gate.js</C>
              </Stack>
            </span>
            <span className="space-y-1 pt-1 @lg:pt-0">
              <In out>answer (JSON, stdout)</In>
              <In out>exit code</In>
            </span>
          </span>
        </Node>
        <Edge className={`${wide} @3xl:col-start-4 @3xl:row-start-2`} />

        <Edge dashed className={`${wide} @3xl:col-start-2 @3xl:row-start-3`} />
        <Node title="Python adapter as a worker process" dashed className="@3xl:col-start-3 @3xl:row-start-3">
          planned; the same JSON protocol
        </Node>
        <Edge dashed className={`${wide} @3xl:col-start-4 @3xl:row-start-3`} />

        <Edge className={narrow}>either way</Edge>
        <div className="flex flex-col @3xl:col-start-5 @3xl:row-[1/4] @3xl:self-center">
          <Node title="Answer + trace">trace optional</Node>
          <Arrow down />
          <Node title="Checks" />
        </div>
      </div>
    </div>
  );
}
