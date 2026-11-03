import type { ReactNode } from "react";
import { FigureHead, Node } from "./kit";

/** Down when the figure stacks, right when it is wide (@3xl). */
function Next({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 py-1 pl-3 text-sm leading-tight text-ink-2 @3xl:flex-col @3xl:justify-center @3xl:gap-0.5 @3xl:px-1 @3xl:py-0 @3xl:text-center">
      <svg aria-hidden viewBox="0 0 24 24" className="size-5 shrink-0 rotate-90 @3xl:rotate-0">
        <path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke="var(--ink-3)" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {children}
    </div>
  );
}

const Truth = ({ children }: { children: ReactNode }) => (
  <span className="mt-1 block">
    <b className="font-bold text-ink">Truth:</b> {children}
  </span>
);

export default function Method3({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="Planned" />
      <div className="grid @3xl:grid-cols-[minmax(0,1.4fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1.3fr)_auto_minmax(0,1.1fr)] @3xl:items-center">
        <div className="space-y-2">
          <Node title="The same version twice (A/A)">
            <Truth>no difference.</Truth>
          </Node>
          <Node title="A mutant">
            e.g. one policy sentence removed.
            <Truth>worse on the cases listed in advance.</Truth>
          </Node>
          <Node title="A real or harmless edit" dashed>
            e.g. a reworded prompt or another model.
            <Truth>not fixed yet. Proposed: a reference measured once with many runs.</Truth>
          </Node>
          <p className="text-sm leading-snug text-ink-2">Each edit is listed before its first run.</p>
        </div>
        <Next />
        <Node title="Recorded runs">K runs × N cases per version; a held-out pool from another week</Node>
        <Next />
        <Node title="Simulator">resamples cases with their runs; no model calls</Node>
        <Next />
        <div className="grid gap-2 @md:grid-cols-2 @3xl:grid-cols-1">
          <Node title="Naive rule (default)" />
          <Node title="Betting rule" />
          <Node title="Betting rule + extra runs" />
          <Node title="Other tools' rules, as documented" />
        </div>
        <Next>scored on</Next>
        <Node title="Measures">
          <ul className="mt-1 list-disc pl-4 [&>li+li]:mt-1">
            <li>false blocks</li>
            <li>missed regressions</li>
            <li>not sure yet at the run limit</li>
            <li>cost and time per decision</li>
          </ul>
        </Node>
      </div>
    </div>
  );
}
