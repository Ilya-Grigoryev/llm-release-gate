import type { ReactNode } from "react";
import { FigureHead, Tag } from "./kit";

type Chip = { label: ReactNode; customer?: boolean };

const model: Chip = { label: "model call" };
const tool = (name?: string): Chip => ({ label: name ? <>tool: <span className="font-mono">{name}</span></> : "tool" });
const customer: Chip = { label: "customer", customer: true };

const APPS: { name: string; steps: Chip[]; state: string | null; answer: ReactNode }[] = [
  { name: "Invoice reader", steps: [model], state: null, answer: <span className="font-mono">{"{vendor, date, total}"}</span> },
  {
    name: "Booking assistant",
    steps: [model, tool("find_customer"), model, tool("cancel_booking"), model],
    state: "{B-104: cancelled}",
    answer: "the reply",
  },
  { name: "Support chat", steps: [customer, model, tool(), model, customer, model], state: "{P-5531: refunded}", answer: "the reply" },
];

const ANSWER_CHECKS = ["field_match", "exact", "contains", "regex", "number", "json_schema", "refusal"];
const TRACE_CHECKS = ["called", "not_called", "order", "max_steps", "active", "actions", "state", "doc_found"];

// Steps, then the world after the run, then the answer: trace checks read the first two, answer checks the last.
const COLS = "sm:grid-cols-[minmax(0,1fr)_8rem_8.5rem]";

function Chips({ steps }: { steps: Chip[] }) {
  return (
    <ol className="flex flex-wrap items-center gap-y-1.5">
      {steps.map((c, i) => (
        <li key={i} className="flex items-center">
          {i > 0 && <span aria-hidden className="h-px w-2 bg-ink-3" />}
          <span className={`rounded border border-ink-3 bg-panel px-2 py-0.5 text-sm leading-snug ${c.customer ? "border-dashed" : ""}`}>
            {c.label}
            {c.customer && (
              <span className="block text-xs text-ink-2">
                a second model (actor <span className="font-mono">user</span>)
              </span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Names({ names }: { names: string[] }) {
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1">
      {names.map((n) => (
        <li key={n} className="rounded bg-canvas px-1.5 font-mono text-xs leading-5 text-ink-2">
          {n}
        </li>
      ))}
    </ul>
  );
}

/** A bracket over the columns it spans, with what the checks under it read. */
function Bracket({ title, className = "", children }: { title: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <span aria-hidden className="block h-2 border-x border-b border-ink-3" />
      <p className="mt-1.5 text-sm font-bold">{title}</p>
      {children}
    </div>
  );
}

/** One kind of run, three lengths. */
export default function Method1() {
  return (
    <div>
      <FigureHead tag="Illustration" />

      <div className={`hidden gap-x-4 border-b border-line pb-1 text-sm text-ink-2 sm:grid ${COLS}`}>
        <span>steps</span>
        <span>state change</span>
        <span>answer</span>
      </div>

      <ul>
        {APPS.map((app) => (
          <li key={app.name} className={`grid gap-x-4 gap-y-2 border-b border-line py-3 sm:items-center ${COLS}`}>
            <div className="min-w-0">
              <p className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="font-bold">{app.name}</span> <Tag>example</Tag>
              </p>
              <Chips steps={app.steps} />
            </div>
            <p className="min-w-0 text-sm">
              <span className="text-ink-2 sm:sr-only">state change: </span>
              {app.state ? <span className="font-mono [overflow-wrap:anywhere]">{app.state}</span> : <span className="text-ink-2">none</span>}
            </p>
            <p className="min-w-0 text-sm">
              <span className="text-ink-2 sm:sr-only">answer: </span>
              {app.answer}
            </p>
          </li>
        ))}
      </ul>

      <div className={`mt-3 grid gap-x-4 gap-y-4 ${COLS}`}>
        <Bracket title="trace checks read the steps and the final state" className="sm:col-span-2">
          <Names names={TRACE_CHECKS} />
        </Bracket>
        <Bracket title="answer checks read the end">
          <Names names={ANSWER_CHECKS} />
        </Bracket>
      </div>
      <p className="mt-4 text-sm">
        <span className="font-mono">function</span>: your own code, given the expected values, the answer and the trace
      </p>
    </div>
  );
}
