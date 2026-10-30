import type { ReactNode } from "react";
import { Verdict } from "../verdict";
import { FigureHead, Key, Node } from "./kit";

/*
 * Wide (@3xl): a 9-column grid, the main line in row 1, the "no" exits in row 2, the budgets path in row 3 (drawn as
 * line segments per cell). Narrow: one column in reading order, the "no" exits to the side.
 */

function Head({ className = "" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={`size-5 shrink-0 ${className}`}>
      <path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke="var(--ink-3)" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A step of the main line: down when the figure stacks, right when it is wide. */
function Next({ label, className }: { label?: string; className: string }) {
  return (
    <div className={`flex items-center gap-1 py-1 pl-3 text-sm text-ink-2 @3xl:flex-col @3xl:justify-center @3xl:gap-0 @3xl:p-0 ${className}`}>
      <Head className="rotate-90 @3xl:rotate-0" />
      {label}
    </div>
  );
}

/** A "no" exit of a question: to the side when the figure stacks, down when it is wide. */
function No({ children, className }: { children: ReactNode; className: string }) {
  return (
    <div className={`flex items-start gap-1 py-1 pl-3 @3xl:flex-col @3xl:items-center @3xl:px-1 @3xl:py-0 ${className}`}>
      <span className="flex shrink-0 items-center gap-1 pt-2 text-sm text-ink-2 @3xl:pt-1">
        <Head className="@3xl:rotate-90" />
        no
      </span>
      <div className="min-w-0 flex-1 space-y-1.5 rounded-md border border-line px-3 py-2 text-sm leading-snug text-ink-2 @3xl:w-full">
        {children}
      </div>
    </div>
  );
}

const M = ({ children }: { children: ReactNode }) => <span className="font-mono text-[0.9em] whitespace-nowrap">{children}</span>;
const seg = "absolute border-ink-3";

export default function WhatItCatches1({}: { alt: string }) {
  return (
    <div className="@container">
      <FigureHead tag="Illustration">
        <Key items={[{ color: "var(--base)", label: "base (main)" }, { color: "var(--cand)", label: "candidate (the request)" }]} />
      </FigureHead>
      <div className="grid @3xl:grid-cols-[minmax(0,0.9fr)_2.5rem_minmax(0,1fr)_2.5rem_minmax(0,1fr)_2.5rem_minmax(0,1fr)_2.5rem_minmax(0,1.15fr)]">
        <Node title="A change in the request" className="@3xl:col-start-1 @3xl:row-start-1 @3xl:self-center" />
        <Next className="@3xl:col-start-2 @3xl:row-start-1" />
        <Node title="Part of the version?" className="@3xl:col-start-3 @3xl:row-start-1 @3xl:self-center">
          config, prompts, code as git sees it
        </Node>
        <No className="@3xl:col-[2/5] @3xl:row-start-2">
          <Verdict kind="unchanged" />
          <p>Nothing runs. For example a README edit, a CI file, a path in <M>ignore</M>.</p>
        </No>
        <Next label="yes" className="@3xl:col-start-4 @3xl:row-start-1" />

        <div className="flex flex-col @3xl:col-start-5 @3xl:row-start-1">
          <span className="hidden flex-1 @3xl:block" />
          <div className="space-y-2">
            <Node title="Base" tone="base">runs the cases</Node>
            <Node title="Candidate" tone="cand">runs the same cases</Node>
          </div>
          <span aria-hidden className="relative hidden min-h-2 flex-1 @3xl:block">
            <span className={`${seg} inset-y-0 left-1/2 border-l`} />
          </span>
        </div>
        <p className="my-1 ml-3 border-l border-ink-3 py-1 pl-3 text-sm text-ink-2 @3xl:hidden">
          Budgets, if set: the candidate goes straight to the barrier as well.
        </p>

        <Next className="@3xl:col-start-6 @3xl:row-start-1" />
        <Node title="Does a case check it?" className="@3xl:col-start-7 @3xl:row-start-1 @3xl:self-center" />
        <No className="@3xl:col-[6/9] @3xl:row-start-2">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Verdict kind="pass" />
            apart from noise
          </p>
          <p>
            Credit limit <M>€30</M> → <M>€40</M>: no case has a credit between <M>€30</M> and <M>€40</M>.
          </p>
        </No>
        <Next label="yes" className="@3xl:col-start-8 @3xl:row-start-1" />

        <div className="flex flex-col @3xl:col-start-9 @3xl:row-start-1">
          <span className="hidden flex-1 @3xl:block" />
          <Node title="The barrier: the naive rule">
            compares the mean scores
            <span className="mt-1.5 block">
              Credit limit <M>€30</M> → <M>€75</M>: case <M>late-cancel-45</M> breaks.
            </span>
          </Node>
          <span aria-hidden className="relative hidden min-h-2 flex-1 @3xl:block">
            <span className={`${seg} inset-y-0 left-1/2 border-l`} />
            <svg viewBox="0 0 10 6" className="absolute top-0 left-1/2 w-2.5 -translate-x-1/2">
              <path d="M1 5.5 5 1l4 4.5" fill="none" stroke="var(--ink-3)" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </div>

        {/* The budgets path, wide layout only: down from the candidate, along the bottom, up into the barrier. */}
        <span aria-hidden className="relative hidden @3xl:col-start-5 @3xl:row-start-2 @3xl:block">
          <span className={`${seg} inset-y-0 left-1/2 border-l`} />
        </span>
        <span aria-hidden className="relative hidden @3xl:col-start-9 @3xl:row-start-2 @3xl:block">
          <span className={`${seg} inset-y-0 left-1/2 border-l`} />
        </span>
        <span aria-hidden className="relative hidden h-8 @3xl:col-start-5 @3xl:row-start-3 @3xl:block">
          <span className={`${seg} top-0 left-1/2 h-1/2 border-l`} />
          <span className={`${seg} top-1/2 right-0 left-1/2 border-t`} />
        </span>
        <span className="relative hidden h-8 items-center justify-center @3xl:col-[6/9] @3xl:row-start-3 @3xl:flex">
          <span aria-hidden className={`${seg} inset-x-0 top-1/2 border-t`} />
          <span className="relative bg-panel px-2 text-sm text-ink-2">budgets, if set</span>
        </span>
        <span aria-hidden className="relative hidden h-8 @3xl:col-start-9 @3xl:row-start-3 @3xl:block">
          <span className={`${seg} top-0 left-1/2 h-1/2 border-l`} />
          <span className={`${seg} top-1/2 right-1/2 left-0 border-t`} />
        </span>
      </div>
    </div>
  );
}
