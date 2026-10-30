import type { ReactNode } from "react";
import { Node } from "./kit";

function Head({ className = "" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={`size-5 shrink-0 ${className}`}>
      <path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke="var(--ink-3)" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Down when the figure stacks, right when it is wide (@3xl); `above` puts the label over the arrow there. */
function Next({ children, className = "", above = false }: { children?: ReactNode; className?: string; above?: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 py-1 pl-3 text-sm leading-tight text-ink-2 ${above ? "@3xl:flex-col-reverse" : "@3xl:flex-col"} @3xl:justify-center @3xl:gap-0.5 @3xl:px-1.5 @3xl:py-0 @3xl:text-center ${className}`}>
      <Head className="rotate-90 @3xl:rotate-0" />
      {children && <span>{children}</span>}
    </div>
  );
}

const tile = "block rounded border border-line bg-paper px-1.5 py-0.5 font-mono text-xs text-ink [overflow-wrap:anywhere]";

export default function Dashboard2({}: { alt: string }) {
  return (
    <div className="@container">
      <div className="grid @3xl:grid-cols-[minmax(0,1fr)_auto_minmax(0,1.25fr)_minmax(0,1fr)_minmax(0,1fr)_auto_minmax(0,1.3fr)] @3xl:items-center">
        <Node title="Your workflow" className="@3xl:col-start-1 @3xl:row-start-1">
          the gate action
        </Node>
        <Next className="@3xl:col-start-2 @3xl:row-start-1">uploads</Next>
        <Node title="Artifacts on GitHub" className="@3xl:col-start-3 @3xl:row-start-1">
          <span className="mt-1.5 block space-y-1">
            <code className={tile}>release-gate-NAME-ATTEMPT</code>
            <code className={tile}>…-cases</code>
          </span>
        </Node>
        <div className="flex flex-col gap-1 @3xl:col-start-4 @3xl:row-start-1 @3xl:gap-1">
          <Next above>when a run finishes, reads the artifacts</Next>
          <Next>
            or by hand: the button <b className="font-bold text-ink">Read runs from GitHub</b>
          </Next>
        </div>
        <Node title="Dashboard" className="@3xl:col-start-5 @3xl:row-start-1">
          GitHub App; stores each gate run
        </Node>
        <Next className="@3xl:col-start-6 @3xl:row-start-1" />
        <div className="flex flex-col @3xl:col-start-7 @3xl:row-start-1 @3xl:self-stretch">
          <span className="hidden flex-1 @3xl:block" />
          <Node title="Your browser" />
          <span aria-hidden className="mx-auto hidden w-px flex-1 bg-ink-3 @3xl:block" />
        </div>
        <div className="ml-3 border-l border-ink-3 py-1 pl-3 text-sm leading-snug text-ink-2 @3xl:col-start-7 @3xl:row-start-2 @3xl:ml-0 @3xl:self-start @3xl:border-l-0 @3xl:p-0">
          <span aria-hidden className="mx-auto hidden h-3 w-px bg-ink-3 @3xl:block" />
          <b className="font-bold text-ink">Sign in with GitHub</b>: you see the repositories where the App is installed and you
          have access.
        </div>
        <div className="mt-4 flex items-center gap-3 @3xl:col-[1/6] @3xl:row-start-2 @3xl:mx-10 @3xl:mt-5 @3xl:flex-col @3xl:gap-1 @3xl:self-start">
          <span aria-hidden className="flex w-20 shrink-0 items-center @3xl:w-full">
            <span className="flex-1 border-t border-ink-3" />
            <svg viewBox="0 0 12 12" className="size-3 shrink-0">
              <path d="M2 2l8 8M10 2l-8 8" fill="none" stroke="var(--ink)" strokeWidth="1.75" strokeLinecap="round" />
            </svg>
            <span className="flex-1 border-t border-ink-3" />
            <svg viewBox="0 0 8 12" className="h-3 w-2 shrink-0">
              <path d="M1.5 1.5 6.5 6l-5 4.5" fill="none" stroke="var(--ink-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="text-sm text-ink-2">CI sends nothing to the dashboard</span>
        </div>
      </div>
    </div>
  );
}
