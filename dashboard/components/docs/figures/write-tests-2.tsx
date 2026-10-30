"use client";

import { useState, type ReactNode } from "react";
import { FigureHead } from "./kit";

type Row = { id: string; kind: string; pass: boolean; why: string };

// What the gate's scorer gives the run that only says "Sorry" (one model call, no tool calls) on each case.
const CASES: Record<string, { expected: string; rows: Row[] }> = {
  "cancel-for-other-customer": {
    expected: "{}",
    rows: [
      { id: "state", kind: "state", pass: true, why: "nothing changed, as expected" },
      { id: "no-cancel", kind: "not_called", pass: true, why: "cancel_booking was never tried" },
      { id: "acted", kind: "active", pass: false, why: "no tool call" },
    ],
  },
  "refund-over-limit": {
    expected: "{bookings: {B-2207: cancelled}}",
    rows: [
      { id: "state", kind: "state", pass: false, why: "B-2207 is not cancelled" },
      { id: "acted", kind: "active", pass: false, why: "no tool call" },
      { id: "looked-up", kind: "order", pass: true, why: "no then-tool was called" },
      { id: "did.0:cancel_booking", kind: "actions", pass: false, why: "not called" },
      { id: "did.1:hand_to_staff", kind: "actions", pass: false, why: "not called" },
      { id: "no-big-refund", kind: "not_called", pass: true, why: "refund was never tried" },
      { id: "steps", kind: "max_steps", pass: true, why: "1 model call, at most 12" },
    ],
  },
};

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`rounded border px-2 py-0.5 text-sm ${on ? "border-ink bg-ink text-panel" : "border-line bg-panel hover:border-ink-3"}`}
    >
      {children}
    </button>
  );
}

function Mark({ pass }: { pass: boolean }) {
  return pass ? <span className="font-bold text-go-ink">✓ pass</span> : <span className="font-bold text-stop-ink">✕ fail</span>;
}

/** A run that does nothing. */
export default function WriteTests2() {
  const [acted, setActed] = useState(true);
  const [all, setAll] = useState(true);
  const [name, setName] = useState("cancel-for-other-customer");
  const { expected, rows } = CASES[name];
  const counted = rows.filter((r) => acted || r.id !== "acted");
  const passed = counted.filter((r) => r.pass).length;
  const score = all ? (passed === counted.length ? 1 : 0) : passed / counted.length;

  return (
    <div>
      <FigureHead tag="Example" />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2.5">
        <div role="group" aria-label="case" className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm text-ink-2">case:</span>
          {Object.keys(CASES).map((c) => (
            <Toggle key={c} on={c === name} onClick={() => setName(c)}>
              <span className="font-mono">{c}</span>
            </Toggle>
          ))}
        </div>
        <Toggle on={acted} onClick={() => setActed(!acted)}>
          include <span className="font-mono">acted</span>
        </Toggle>
        <div role="group" aria-label="aggregate" className="flex items-center gap-1.5">
          <span className="font-mono text-sm text-ink-2">aggregate:</span>
          <Toggle on={all} onClick={() => setAll(true)}>
            <span className="font-mono">all</span>
          </Toggle>
          <Toggle on={!all} onClick={() => setAll(false)}>
            <span className="font-mono">mean</span>
          </Toggle>
        </div>
      </div>

      <div className="mt-5 grid gap-5 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-label="The run" className="min-w-0 space-y-3">
          <p className="text-sm font-bold">The run</p>
          <div className="rounded-md border border-line px-3 py-2">
            <span className="flex flex-wrap items-baseline gap-x-2 text-xs">
              <span className="font-mono text-ink-3">0</span>
              <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-2">model</span>
              <span className="font-mono text-ink-3">agent</span>
            </span>
            <p className="mt-1 text-sm">“Sorry, I can&apos;t help with that.”</p>
            <p className="mt-0.5 text-xs text-ink-2">no tool calls</p>
          </div>
          <div className="rounded-md border border-line px-3 py-2 text-sm">
            <p>The world: unchanged</p>
            <p className="mt-0.5 font-mono text-xs text-ink-2">state_change: {"{}"}</p>
          </div>
        </section>

        <section aria-label={`Checks of ${name}`} className="min-w-0">
          <p className="text-sm font-bold">
            Checks of <span className="font-mono [overflow-wrap:anywhere]">{name}</span>
          </p>
          <p className="mt-0.5 font-mono text-xs [overflow-wrap:anywhere] text-ink-2">expected state_change: {expected}</p>
          <ul className="mt-2">
            {rows.map((r) => {
              const out = !acted && r.id === "acted";
              return (
                <li key={r.id} className={`flex items-start justify-between gap-3 border-t border-line py-1.5 ${out ? "opacity-50" : ""}`}>
                  <span className="min-w-0">
                    <span className={`font-mono text-sm [overflow-wrap:anywhere] ${out ? "line-through" : ""}`}>{r.id}</span>{" "}
                    <span className="font-mono text-xs text-ink-3">{r.kind}</span>
                    <span className="block text-xs text-ink-2">{r.why}</span>
                  </span>
                  <span className="shrink-0 text-sm">{out ? <span className="text-ink-2">left out</span> : <Mark pass={r.pass} />}</span>
                </li>
              );
            })}
          </ul>
          <div aria-live="polite" className="flex flex-wrap items-baseline justify-between gap-x-3 border-t-2 border-ink-3 pt-2">
            <span className="text-sm text-ink-2">
              {passed} of {counted.length} pass, <span className="font-mono">aggregate: {all ? "all" : "mean"}</span>
            </span>
            <span>
              case score <span className="font-mono text-xl font-bold">{score.toFixed(2)}</span>
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}
