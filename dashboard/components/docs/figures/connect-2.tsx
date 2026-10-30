"use client";

import { useState } from "react";
import { Json } from "@/components/json";
import { FigureHead } from "./kit";

type Call = { id: string; name: string; args: Record<string, string> };
type Step = {
  kind: "llm" | "tool" | "retrieval";
  actor: "agent" | "user";
  status?: string;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: null;
  text?: string;
  tool_calls?: Call[];
  call_id?: string;
  name?: string;
  args?: Record<string, string>;
  result?: unknown;
  query?: string;
  docs?: { id: string }[];
};

const MODEL = "gpt-4.1-mini-2025-04-14";
const llm = (actor: Step["actor"], tokens_in: number, tokens_out: number, rest: Partial<Step>): Step => ({
  kind: "llm",
  actor,
  status: "ok",
  model: MODEL,
  tokens_in,
  tokens_out,
  cost_usd: null,
  ...rest,
});

// The trace from the program's answer above, in the order the gate numbers it.
const STEPS: Step[] = [
  llm("user", 210, 14, { text: "I was charged twice for order 1182." }),
  { kind: "retrieval", actor: "agent", query: "charged twice", docs: [{ id: "kb-double-charge" }] },
  llm("agent", 820, 22, { tool_calls: [{ id: "c1", name: "find_payments", args: { order_id: "1182" } }] }),
  {
    kind: "tool",
    actor: "agent",
    call_id: "c1",
    name: "find_payments",
    args: { order_id: "1182" },
    status: "ok",
    result: [
      { id: "P-5530", eur: 12.0 },
      { id: "P-5531", eur: 12.0 },
    ],
  },
  llm("agent", 880, 20, { tool_calls: [{ id: "c2", name: "refund_payment", args: { payment_id: "P-5531" } }] }),
  { kind: "tool", actor: "agent", call_id: "c2", name: "refund_payment", args: { payment_id: "P-5531" }, status: "ok", result: { refund: "R-0412" } },
  llm("agent", 935, 18, { text: "I have refunded the second payment, P-5531. Your refund reference is R-0412." }),
  llm("user", 260, 5, { text: "Thanks, that is all." }),
];

const END = {
  final_state: { payments: { "P-5530": "paid", "P-5531": "refunded" } },
  state_change: { payments: { "P-5531": "refunded" } },
  stop: "done",
};

// Example prices per 1M tokens.
const PRICE = { in: 0.4, out: 1.6 };
const LANE = { agent: "agent", user: "user (simulated customer)" };

const n = (x: number) => x.toLocaleString("en-US");
const args = (a: Record<string, string>) =>
  `(${Object.entries(a)
    .map(([k, v]) => `${k}: "${v}"`)
    .join(", ")})`;
// A value as YAML's flow style writes it: {payments: {P-5531: refunded}}.
const flow = (v: unknown): string =>
  v !== null && typeof v === "object"
    ? `{${Object.entries(v)
        .map(([k, x]) => `${k}: ${flow(x)}`)
        .join(", ")}}`
    : String(v);
const firstWords = (text: string, count = 8) => {
  const words = text.split(" ");
  return words.length > count ? `${words.slice(0, count).join(" ")} …` : text;
};

function total(actor: Step["actor"]) {
  const calls = STEPS.filter((s) => s.kind === "llm" && s.actor === actor);
  const tin = calls.reduce((a, s) => a + (s.tokens_in ?? 0), 0);
  const tout = calls.reduce((a, s) => a + (s.tokens_out ?? 0), 0);
  return { calls: calls.length, tin, tout, usd: (tin * PRICE.in + tout * PRICE.out) / 1e6 };
}

function Badge({ children }: { children: string }) {
  return <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-2">{children}</span>;
}

function CallId({ id }: { id: string }) {
  return <span className="rounded border border-ink-3 px-1 font-mono text-xs text-ink">{id}</span>;
}

/** What a step card shows: a model call in full, a retrieval or a tool call as one short line. */
function Body({ step }: { step: Step }) {
  if (step.kind === "llm") {
    return (
      <>
        <span className="flex flex-wrap gap-x-3 font-mono text-xs [overflow-wrap:anywhere] text-ink-3">
          <span>{step.model}</span>
          <span>
            {step.tokens_in} → {step.tokens_out} tokens
          </span>
        </span>
        {step.text && <span className="mt-1 block text-sm">“{firstWords(step.text)}”</span>}
        {step.tool_calls?.map((c) => (
          <span key={c.id} className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-xs [overflow-wrap:anywhere] text-ink-2">
            calls {c.name}
            {args(c.args)} <CallId id={c.id} />
          </span>
        ))}
      </>
    );
  }
  if (step.kind === "retrieval") {
    return (
      <span className="block font-mono text-xs [overflow-wrap:anywhere] text-ink-2">
        {step.docs?.map((d) => d.id).join(", ")} <span className="font-sans text-ink-3">for “{step.query}”</span>
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-1.5 font-mono text-xs [overflow-wrap:anywhere] text-ink-2">
      {args(step.args ?? {})} <span className="font-sans">{step.status}</span> {step.call_id && <CallId id={step.call_id} />}
    </span>
  );
}

/** One run of the support chat, step by step. */
export default function Connect2() {
  const [open, setOpen] = useState<number[]>([]);
  const toggle = (i: number) => setOpen((o) => (o.includes(i) ? o.filter((x) => x !== i) : [...o, i]));

  return (
    <div>
      <FigureHead tag="Example: made-up run">
        <p className="text-sm text-ink-2">Click a step for its fields.</p>
      </FigureHead>

      <div aria-hidden className="mb-2 hidden grid-cols-2 gap-6 border-b border-line pb-1.5 text-sm font-bold sm:grid">
        <span>{LANE.agent}</span>
        <span>{LANE.user}</span>
      </div>

      <ol aria-label="Steps of the run" className="grid gap-y-2.5">
        {STEPS.map((step, seq) => {
          const isOpen = open.includes(seq);
          const small = step.kind !== "llm";
          const kind = { llm: "model", tool: "tool", retrieval: "retrieval" }[step.kind];
          const label = step.kind === "llm" ? "" : step.kind === "tool" ? step.name : "documents";
          return (
            <li key={seq} className="grid grid-cols-[2.75rem_minmax(0,1fr)] sm:grid-cols-2 sm:gap-x-6">
              <span className="pt-2 text-xs text-ink-3 sm:sr-only">{step.actor}</span>
              <div className={`col-start-2 min-w-0 sm:row-start-1 ${step.actor === "user" ? "sm:col-start-2" : "sm:col-start-1"}`}>
                {step.call_id && (
                  <span aria-hidden className="-mt-2.5 ml-8 block h-2.5 border-l border-ink-3" />
                )}
                <button
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={`connect-2-step-${seq}`}
                  onClick={() => toggle(seq)}
                  className={`block rounded-md border bg-panel text-left hover:border-ink-3 ${
                    isOpen ? "border-ink-3" : "border-line"
                  } ${small ? "ml-4 w-[calc(100%-1rem)] px-2.5 py-1.5" : "w-full px-3 py-2"}`}
                >
                  <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                    <span className="font-mono text-ink-3">{seq}</span>
                    <Badge>{kind}</Badge>
                    {label && <span className={`font-medium text-ink ${step.kind === "tool" ? "font-mono" : ""}`}>{label}</span>}
                  </span>
                  <span className="mt-1 block">
                    <Body step={step} />
                  </span>
                </button>
                <div id={`connect-2-step-${seq}`} hidden={!isOpen} className="mt-1.5">
                  {isOpen && <Json value={{ seq, ...step }} />}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <dl className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-2 sm:gap-6">
        {(["agent", "user"] as const).map((actor) => {
          const t = total(actor);
          return (
            <div key={actor} className="min-w-0">
              <dt className="text-sm font-bold">{LANE[actor]}</dt>
              <dd className="font-mono text-sm text-ink-2">
                {t.calls} model calls, {n(t.tin)} in, {n(t.tout)} out, ${t.usd.toFixed(5)}
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="mt-1.5 text-sm text-ink-2">
        At example prices: <span className="font-mono">$0.40</span> per 1M input tokens, <span className="font-mono">$1.60</span> per 1M
        output tokens.
      </p>

      <dl className="mt-4 space-y-1 rounded-md bg-canvas px-3 py-2 font-mono text-xs [overflow-wrap:anywhere] text-ink-2">
        {Object.entries(END).map(([k, v]) => (
          <div key={k}>
            <dt className="inline text-ink">{k}: </dt>
            <dd className="inline">{flow(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
