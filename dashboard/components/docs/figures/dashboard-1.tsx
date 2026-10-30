import type { ReactNode } from "react";
import { FigureHead } from "./kit";

type Step = { kind: "model" | "tool"; label: string; code?: boolean };

type Run = {
  title: string;
  color: string;
  head: { score: string; tokens: string; time: string };
  answer: string;
  checks: [name: string, pass: boolean][];
  steps: Step[];
  change: string;
};

const MODEL = "gpt-4.1-mini-2025-04-14";
const DIFFERS = new Set(["cancelled", "no-fee-waiver"]);

const call = (tool: string): Step[] => [
  { kind: "model", label: `calls ${tool}`, code: true },
  { kind: "tool", label: tool, code: true },
];

const SIDES: Run[] = [
  {
    title: "Base · target branch",
    color: "var(--base)",
    head: { score: "1.00", tokens: "1240 → 96 tokens", time: "3.1 s" },
    answer: "Booking B-1042 is cancelled. Because it is so close to the date, the late-cancellation fee applies.",
    checks: [["cancelled", true], ["acted", true], ["looked-up", true], ["no-fee-waiver", true], ["steps", true]],
    steps: [...call("find_booking"), ...call("cancel_booking"), { kind: "model", label: "reply" }],
    change: "{bookings: {B-1042: cancelled}}",
  },
  {
    title: "Candidate · pull request",
    color: "var(--cand)",
    head: { score: "0.00", tokens: "1610 → 118 tokens", time: "4.2 s" },
    answer: "Booking B-1042 is cancelled, and I have waived the late-cancellation fee for you.",
    checks: [["cancelled", false], ["acted", true], ["looked-up", true], ["no-fee-waiver", false], ["steps", true]],
    steps: [...call("find_booking"), ...call("waive_fee"), ...call("cancel_booking"), { kind: "model", label: "reply" }],
    change: "{bookings: {B-1042: cancelled}, fees: {B-1042: waived}}",
  },
];

function Label({ children }: { children: ReactNode }) {
  return <p className="mb-1.5 text-xs text-ink-3">{children}</p>;
}

function Side({ run }: { run: Run }) {
  return (
    <div className="min-w-0 space-y-4 rounded-lg border border-line bg-panel p-3 sm:p-4">
      <p className="flex items-center gap-2 font-bold">
        <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ background: run.color }} />
        {run.title}
      </p>
      <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-ink-2">
        <span>
          score <b className="font-mono text-lg text-ink tabular-nums">{run.head.score}</b>
        </span>
        <span className="font-mono text-xs break-all">{MODEL}</span>
        <span className="font-mono text-xs tabular-nums">{run.head.tokens}</span>
        <span className="font-mono text-xs tabular-nums">{run.head.time}</span>
      </p>
      <div>
        <Label>Answer</Label>
        <p className="rounded-md bg-paper p-2.5 text-sm">{run.answer}</p>
      </div>
      <div>
        <Label>Checks</Label>
        <ul role="list" className="grid list-none gap-1 pl-0">
          {run.checks.map(([name, pass]) => (
            <li key={name} className={`mt-0 flex items-center gap-2 font-mono text-xs ${DIFFERS.has(name) ? "font-bold text-ink" : "text-ink-2"}`}>
              <span aria-hidden className={pass ? "text-go-ink" : "text-stop-ink"}>
                {pass ? "✓" : "✕"}
              </span>
              <span className="sr-only">{pass ? "pass" : "fail"}</span>
              {name}
              {DIFFERS.has(name) && <span className="font-sans font-normal text-ink-3">differs</span>}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <Label>Steps</Label>
        <ol role="list" className="list-none space-y-1.5 border-l border-line pl-3">
          {run.steps.map((step, i) => (
            <li key={i} className="mt-0 flex flex-wrap items-baseline gap-x-2 text-xs">
              <span className="font-mono text-ink-3">{i + 1}</span>
              <span className="rounded bg-paper px-1.5 py-0.5 text-ink-2">{step.kind}</span>
              <span className={step.code ? "font-mono break-all text-ink" : "text-ink-2"}>{step.label}</span>
            </li>
          ))}
        </ol>
      </div>
      <div>
        <Label>state change</Label>
        <p className="font-mono text-xs break-words text-ink-2">{run.change}</p>
      </div>
    </div>
  );
}

/** A case on the dashboard: a drawn mock of the case page. */
export default function Dashboard1({}: { alt: string }) {
  return (
    <>
      <FigureHead tag="Example: a drawn mock, not a screenshot" />
      <div className="rounded-md border border-line bg-paper p-3 sm:p-4">
        <p className="font-mono text-lg font-bold break-all">cancel-after-deadline</p>
        <p className="mt-1 text-sm text-ink-2">Score 1.00 → 0.00 · checks that differ: cancelled, no-fee-waiver</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="min-w-0 rounded-lg border border-line bg-panel p-3 sm:p-4">
            <p className="mb-2 font-bold">Input</p>
            <Label>request</Label>
            <p className="text-sm">Hi, please cancel booking B-1042 for tomorrow. I know it is late.</p>
          </div>
          <div className="min-w-0 rounded-lg border border-line bg-panel p-3 sm:p-4">
            <p className="mb-2 font-bold">Expected</p>
            <p className="font-mono text-xs break-words text-ink-2">state_change: {"{bookings: {B-1042: cancelled}}"}</p>
          </div>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {SIDES.map((run) => (
            <Side key={run.title} run={run} />
          ))}
        </div>
      </div>
    </>
  );
}
