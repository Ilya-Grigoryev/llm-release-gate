"use client";

import { useState, type ReactNode } from "react";
import { FigureHead } from "./kit";

type Part = "answer" | "steps" | "retrieval" | "after" | "all";
type Tile = { kind: string; reads: Part; example: string };

// Grouped by the question they answer, as in the table above; `not_called` answers two.
const GROUPS: { question: string; tiles: Tile[] }[] = [
  {
    question: "The result",
    tiles: [
      { kind: "field_match", reads: "answer", example: "{id: fields, kind: field_match, fields: {total: {type: number}}}" },
      { kind: "exact", reads: "answer", example: "{id: status, kind: exact, field: status, value: confirmed}" },
      { kind: "contains", reads: "answer", example: "{id: fee, kind: contains, field: reply, value: cancellation fee}" },
      { kind: "regex", reads: "answer", example: String.raw`{id: ref, kind: regex, field: reply, pattern: "B-\\d+"}` },
      { kind: "number", reads: "answer", example: "{id: total, kind: number, field: total, expected: total, tol: 0.01}" },
      { kind: "json_schema", reads: "answer", example: "{id: shape, kind: json_schema, schema: {type: object, required: [vendor, total]}}" },
      { kind: "refusal", reads: "answer", example: "{id: declines, kind: refusal, value: true}" },
    ],
  },
  {
    question: "The actions",
    tiles: [
      { kind: "called", reads: "steps", example: "{id: escalated, kind: called, tool: hand_to_staff}" },
      { kind: "not_called", reads: "steps", example: "{id: no-cancel, kind: not_called, tool: cancel_booking}" },
      { kind: "order", reads: "steps", example: "{id: looked-up, kind: order, first: find_customer, then: [cancel_booking, refund]}" },
      { kind: "actions", reads: "steps", example: "{id: did, kind: actions, actions: [{tool: cancel_booking, args: {booking_id: B-2207}}]}" },
      { kind: "active", reads: "steps", example: "{id: acted, kind: active}" },
      { kind: "doc_found", reads: "retrieval", example: "{id: sources, kind: doc_found, ids: [kb-refunds]}" },
    ],
  },
  { question: "The state of the world", tiles: [{ kind: "state", reads: "after", example: "{id: state, kind: state, key: state_change}" }] },
  {
    question: "The limits",
    tiles: [
      { kind: "max_steps", reads: "steps", example: "{id: steps, kind: max_steps, max: 12}" },
      { kind: "not_called", reads: "steps", example: "{id: no-big-refund, kind: not_called, tool: refund, args: {amount_eur: {gt: 50}}}" },
    ],
  },
  {
    question: "Anything else",
    tiles: [
      {
        kind: "function",
        reads: "all",
        example: '{id: names-booking, kind: function, function: "booking_assistant.checks:names_the_booking", booking: B-2207}',
      },
    ],
  },
];

const READS: Record<Part, string> = {
  answer: "reads the answer",
  steps: "reads the steps",
  retrieval: "reads the retrieval step",
  after: "reads the world after the run",
  all: "gets the expected values, the answer and the trace",
};

const STEPS = [
  { kind: "model", label: "" },
  { kind: "tool", label: "find_customer" },
  { kind: "retrieval", label: "kb-refunds", note: "the refund policy" },
  { kind: "tool", label: "cancel_booking" },
  { kind: "tool", label: "hand_to_staff" },
];

const BOOKINGS = [
  { id: "B-2206", before: "confirmed", after: "confirmed" },
  { id: "B-2207", before: "confirmed", after: "cancelled" },
  { id: "B-2208", before: "confirmed", after: "confirmed" },
];

const ring = (on: boolean) => (on ? "outline-2 outline-offset-4 outline-ink" : "");

function Band({ title, lit, children }: { title: string; lit: boolean; children: ReactNode }) {
  return (
    <section aria-label={title} className={`min-w-0 rounded-md border border-line bg-panel p-3 ${ring(lit)}`}>
      <p className="mb-2 text-sm font-bold">{title}</p>
      {children}
    </section>
  );
}

function World({ when, lit }: { when: "before" | "after"; lit: boolean }) {
  return (
    <div className={`rounded ${ring(lit)}`}>
      <p className="text-sm text-ink-2">{when}</p>
      <table className="mt-0.5 w-full table-fixed text-sm">
        <tbody>
          {BOOKINGS.map((b) => {
            const changed = b.before !== b.after;
            return (
              <tr key={b.id} className="border-t border-line">
                <td className="w-[4.5rem] py-0.5 pr-2 font-mono">{b.id}</td>
                <td className={`py-0.5 ${changed && when === "after" ? "font-bold" : ""}`}>
                  {b[when]}
                  {changed && when === "after" && <span className="ml-1.5 text-xs font-normal text-ink-2">changed</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {when === "after" && (
        <p className="mt-1.5 font-mono text-xs text-ink-2">state_change: {"{bookings: {B-2207: cancelled}}"}</p>
      )}
    </div>
  );
}

/** What each check reads. */
export default function WriteTests1() {
  const [picked, setPicked] = useState<string | null>(null);
  const tile = GROUPS.flatMap((g) => g.tiles.map((t) => ({ ...t, key: `${g.question}:${t.kind}` }))).find((t) => t.key === picked);
  const reads = tile?.reads;
  const lit = (part: Part) => reads === part || reads === "all";

  return (
    <div onKeyDown={(e) => e.key === "Escape" && setPicked(null)}>
      <FigureHead tag="Example run">
        <p className="text-sm text-ink-2">Pick a check to see what it reads; Escape clears.</p>
      </FigureHead>

      <div className="flex flex-wrap gap-x-6 gap-y-3">
        {GROUPS.map((g) => (
          <div key={g.question} className="min-w-0">
            <p className="mb-1 text-sm text-ink-2">{g.question}</p>
            <ul className="flex flex-wrap gap-1.5">
              {g.tiles.map((t) => {
                const key = `${g.question}:${t.kind}`;
                const on = key === picked;
                return (
                  <li key={key}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => setPicked(on ? null : key)}
                      className={`rounded border px-2 py-0.5 font-mono text-sm ${on ? "border-ink bg-ink text-panel" : "border-line bg-panel hover:border-ink-3"}`}
                    >
                      {t.kind}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div aria-live="polite" className="mt-4 min-h-14 rounded-md bg-canvas px-3 py-2 text-sm">
        {tile ? (
          <>
            <p>
              <code className="font-mono">{tile.kind}</code> {READS[tile.reads]}.
            </p>
            <p className="mt-0.5 font-mono text-xs [overflow-wrap:anywhere] text-ink-2">{tile.example}</p>
          </>
        ) : (
          <p className="text-ink-2">The run below has three parts a check can read: its steps, the world before and after, and the answer.</p>
        )}
      </div>

      <div className="mt-5 grid gap-5 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Band title="Steps" lit={lit("steps")}>
          <ol className="space-y-1.5">
            {STEPS.map((s, seq) => (
              <li key={seq} className={`rounded px-1 py-0.5 ${ring(s.kind === "retrieval" && reads === "retrieval")}`}>
                <span className="flex flex-wrap items-baseline gap-x-2 text-xs">
                  <span className="font-mono text-ink-3">{seq}</span>
                  <span className="rounded bg-canvas px-1.5 py-0.5 font-medium text-ink-2">{s.kind}</span>
                  {s.label && <span className="font-mono font-medium break-all text-ink">{s.label}</span>}
                  <span className="font-mono text-ink-3">agent</span>
                </span>
                {s.note && <span className="mt-0.5 block text-xs text-ink-2">{s.note}</span>}
              </li>
            ))}
          </ol>
        </Band>

        <Band title="World" lit={false}>
          <div className="space-y-3">
            <World when="before" lit={false} />
            <World when="after" lit={lit("after")} />
          </div>
        </Band>

        <Band title="Answer" lit={lit("answer")}>
          <p className="rounded-lg rounded-tl-none border border-line bg-paper px-3 py-2 text-sm">
            Booking <span className="font-mono">B-2207</span> is cancelled. Our staff will handle your €80 refund.
          </p>
        </Band>
      </div>
    </div>
  );
}
