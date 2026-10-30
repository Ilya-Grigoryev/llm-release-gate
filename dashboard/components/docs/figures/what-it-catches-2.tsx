"use client";

import { useId, useRef, useState, type ReactNode } from "react";

const code = (text: string) => <code className="font-mono text-[0.9em]">{text}</code>;

type Stage = "today" | "planned" | "maybe later" | "idea";
type Tile = { name: string; what: ReactNode; yaml?: string; stage?: Stage };

/** The check library: what each kind looks at and one line of a case file (from Write tests). */
const GROUPS: { title: string; tiles: Tile[] }[] = [
  {
    title: "Answer",
    tiles: [
      { name: "field_match", what: "Each expected field of the answer matches; one result per field.", yaml: "{id: fields, kind: field_match, fields: {total: {type: number}}}" },
      { name: "exact", what: "The text equals the value, ignoring spaces around it.", yaml: "{id: status, kind: exact, field: status, value: confirmed}" },
      { name: "contains", what: "The text contains the value, ignoring case.", yaml: "{id: fee, kind: contains, field: reply, value: cancellation fee}" },
      { name: "regex", what: "The pattern matches somewhere in the text.", yaml: '{id: ref, kind: regex, field: reply, pattern: "B-\\\\d+"}' },
      { name: "number", what: <>The number is within {code("tol")} of the value, also in an amount such as $7.80.</>, yaml: "{id: total, kind: number, field: total, expected: total, tol: 0.01}" },
      { name: "json_schema", what: "The value is valid against a JSON Schema.", yaml: "{id: shape, kind: json_schema, schema: {type: object, required: [vendor, total]}}" },
      { name: "refusal", what: <>With {code("value: true")}, the answer field is present and {code("null")}: the app declined.</>, yaml: "{id: declines, kind: refusal, value: true}" },
    ],
  },
  {
    title: "Trace",
    tiles: [
      { name: "called", what: "The agent called the tool with matching arguments, and the call did not fail.", yaml: "{id: escalated, kind: called, tool: hand_to_staff}" },
      { name: "not_called", what: "The agent never tried the tool with such arguments; a call the tool refused counts as tried.", yaml: "{id: no-big-refund, kind: not_called, tool: refund, args: {amount_eur: {gt: 50}}}" },
      { name: "order", what: <>Every call of a {code("then")} tool comes after a call of {code("first")}.</>, yaml: "{id: looked-up, kind: order, first: find_customer, then: [cancel_booking, refund]}" },
      { name: "max_steps", what: <>The agent made at most {code("max")} answered model calls.</>, yaml: "{id: steps, kind: max_steps, max: 12}" },
      { name: "active", what: "The agent made at least one tool call that did not fail.", yaml: "{id: acted, kind: active}" },
      { name: "actions", what: "Each expected action: the agent called that tool with matching arguments; one result per action.", yaml: "{id: did, kind: actions, actions: [{tool: cancel_booking, args: {booking_id: B-2207}}]}" },
      { name: "state", what: "The final state, or the state change, equals the expected one.", yaml: "{id: state, kind: state, key: state_change}" },
      { name: "doc_found", what: "The share of the expected documents the agent retrieved.", yaml: "{id: sources, kind: doc_found, ids: [kb-refunds]}" },
    ],
  },
  {
    title: "Yours",
    tiles: [
      {
        name: "function",
        what: "Calls a Python function you write with the expected values, the answer and the trace; it returns true, false or a share.",
        yaml: '{id: names-booking, kind: function, function: "booking_assistant.checks:names_the_booking", booking: B-2207}',
      },
    ],
  },
  {
    title: "Not built yet",
    tiles: [
      { name: "shared checks for a set", stage: "planned", what: "A file next to the cases holds checks every case shares; a case can override one or turn it off." },
      { name: "new check kinds", stage: "planned", what: <>New kinds join the library in later releases; until then a {code("function")} check covers them.</> },
      { name: "proposed checks you approve", stage: "maybe later", what: "The gate runs the base several times and suggests as checks what stayed the same in every run; you approve the ones you want." },
      { name: "LLM judge, opt-in", stage: "maybe later", what: "A check a team turns on for qualities code cannot express, such as politeness." },
      { name: "relative budget", stage: "idea", what: "A budget against the base, such as no more than 20 % more expensive; it needs its own design first." },
      { name: "trajectory matching", stage: "idea", what: "Matching a whole run: at least these calls, nothing outside these calls, arguments as a subset." },
      { name: "coverage report", stage: "idea", what: "The tools and rules that no check looks at." },
    ],
  },
];

/** Built today: a filled tile; planned or maybe later: outlined; an idea: dashed. */
const LOOK: Record<Stage, string> = {
  today: "bg-[color-mix(in_srgb,var(--ink)_8%,var(--panel))]",
  planned: "",
  "maybe later": "",
  idea: "border-dashed",
};

/** The check library. */
export default function WhatItCatches2({}: { alt: string }) {
  const id = useId();
  const [open, setOpen] = useState<string | null>(null);
  const tiles = useRef<Record<string, HTMLButtonElement | null>>({});

  const close = () => {
    if (!open) return;
    tiles.current[open]?.focus();
    setOpen(null);
  };

  return (
    <div onKeyDown={(e) => e.key === "Escape" && close()}>
      <div className="space-y-5">
        {GROUPS.map((group, g) => {
          const shown = group.tiles.find((t) => t.name === open);
          const panel = `${id}-${g}`;
          return (
            <div key={group.title}>
              <p className="mb-2 font-bold">{group.title}</p>
              <ul role="list" className="grid list-none grid-cols-2 gap-2 pl-0 sm:grid-cols-3 lg:grid-cols-4">
                {group.tiles.map((tile) => {
                  const stage = tile.stage ?? "today";
                  return (
                    <li key={tile.name} className="mt-0 flex">
                      <button
                        type="button"
                        ref={(el) => {
                          tiles.current[tile.name] = el;
                        }}
                        aria-expanded={open === tile.name}
                        aria-controls={panel}
                        onClick={() => setOpen(open === tile.name ? null : tile.name)}
                        className={`flex w-full min-w-0 flex-col items-start rounded-md border-[1.5px] px-2.5 py-1.5 text-left ${LOOK[stage]} ${
                          open === tile.name ? "border-ink" : stage === "today" ? "border-transparent hover:border-ink-3" : "border-ink-3 hover:border-ink"
                        }`}
                      >
                        <span className={`${tile.stage ? "text-sm leading-snug text-ink-2" : "font-mono text-sm text-ink"} break-words`}>{tile.name}</span>
                        {tile.stage && <span className="mt-0.5 text-xs text-ink-3">{tile.stage}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div id={panel} hidden={!shown} className="mt-2 rounded-md border border-line bg-paper p-3 text-sm">
                {shown && <Detail tile={shown} />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Detail({ tile }: { tile: Tile }) {
  return (
    <>
      <p>
        <span className={tile.stage ? "font-bold" : "font-mono font-bold"}>{tile.name}</span>
        {tile.stage && <span className="text-ink-3">, {tile.stage}</span>}
        <span className="text-ink-2">: </span>
        {tile.what}
      </p>
      {tile.yaml && <pre className="mt-2 overflow-x-auto font-mono text-xs leading-relaxed text-ink-2">{`- ${tile.yaml}`}</pre>}
    </>
  );
}
