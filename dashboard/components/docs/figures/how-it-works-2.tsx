"use client";

import { useId, useState, type ReactNode } from "react";
import { FigureHead, LampDot } from "./kit";

const code = (text: string) => <span className="font-mono text-[0.9em]">{text}</span>;

/** A row of the tree. `counts`: part of the version (ink), not (grey, with `why`), or a folder of both (null). */
type Row = { path: string; name: string; depth?: number; counts: boolean | null; why?: ReactNode; inline?: string };

const TREE: Row[] = [
  { path: ".github/workflows/ci.yml", name: ".github/workflows/ci.yml", counts: false, why: "CI" },
  { path: "booking_assistant/", name: "booking_assistant/", counts: true },
  { path: "booking_assistant/agent.py", name: "agent.py", depth: 1, counts: true },
  { path: "booking_assistant/tools.py", name: "tools.py", depth: 1, counts: true },
  { path: "configs/booking.yaml", name: "configs/booking.yaml", counts: true },
  { path: "docs/", name: "docs/", counts: null },
  { path: "docs/guide.md", name: "guide.md", depth: 1, counts: false, why: "documentation" },
  { path: "docs/kb/refunds.md", name: "kb/refunds.md", depth: 1, counts: true, why: <>taken back by {code('"!docs/kb/"')}</> },
  { path: "golden/booking/", name: "golden/booking/", counts: false, why: "test set" },
  { path: "golden/booking/cancel-after-deadline.yaml", name: "cancel-after-deadline.yaml", depth: 1, counts: false },
  { path: "prompts/system.md", name: "prompts/system.md", counts: true },
  { path: "web/index.html", name: "web/index.html", counts: false, why: "ignored" },
  { path: "gate.yaml", name: "gate.yaml", counts: false, why: "gate settings", inline: 'ignore: [web/, "!docs/kb/"]' },
  { path: "README.md", name: "README.md", counts: false, why: "documentation" },
  { path: "uv.lock", name: "uv.lock", counts: true },
];

type Change = { label: ReactNode; file: string; runs: boolean; why: ReactNode; note?: ReactNode };

/** The outcomes are the gate's: what `pr` decides for a request that touches only this file. */
const CHANGES: Change[] = [
  { label: "edit the system prompt", file: "prompts/system.md", runs: true, why: "The config names this prompt, so its bytes are part of the version." },
  { label: <>edit {code("README.md")}</>, file: "README.md", runs: false, why: "Documentation does not count." },
  {
    label: <>edit {code("docs/kb/refunds.md")}</>,
    file: "docs/kb/refunds.md",
    runs: true,
    why: <>A root {code("docs/")} is documentation, but {code("gate.yaml")} takes {code("docs/kb/")} back with {code('"!docs/kb/"')}.</>,
  },
  { label: <>update {code("uv.lock")}</>, file: "uv.lock", runs: true, why: "The lock file is code: every pipeline gets a new version." },
  {
    label: "edit a test case",
    file: "golden/booking/cancel-after-deadline.yaml",
    runs: false,
    why: <>The test set that {code("gate.yaml")} names does not count.</>,
    note: <>This request changes the test set of {code("booking")}.</>,
  },
  { label: <>edit {code("web/index.html")}</>, file: "web/index.html", runs: false, why: <>{code("web/")} is listed in {code("ignore")}.</> },
  {
    label: <>raise {code("delta")} in {code("gate.yaml")}</>,
    file: "gate.yaml",
    runs: false,
    why: <>The gate&apos;s settings do not count.</>,
    note: (
      <>
        ⚙️ This request changes the gate&apos;s rules for {code("booking")} (gate.yaml or its prices). They apply after merge; until
        then the gate keeps the target branch&apos;s.
      </>
    ),
  },
];

function Line({ row, touched }: { row: Row; touched: boolean }) {
  const ink = row.counts === false ? "text-ink-3" : row.counts ? "text-ink" : "text-ink-2";
  return (
    <li
      className={`mt-0 flex flex-wrap items-baseline justify-between gap-x-3 rounded py-0.5 pr-1.5 ${touched ? "bg-paper outline-1 outline-ink" : ""}`}
      style={{ paddingLeft: `${0.375 + (row.depth ?? 0) * 1.25}rem` }}
    >
      <span className={`min-w-0 font-mono text-sm ${ink} ${touched ? "font-bold" : ""}`}>
        <span className="break-all">{row.name}</span>
        {row.inline && <span className="ml-2 inline-block font-normal whitespace-nowrap text-ink-2">{row.inline}</span>}
      </span>
      <span className="flex items-baseline gap-2 text-sm">
        {row.why && <span className={row.counts ? "text-ink-2" : "text-ink-3"}>{row.why}</span>}
        {touched && <span className="rounded-full border border-ink px-2 text-xs leading-5 text-ink">edited</span>}
      </span>
    </li>
  );
}

/** What counts as the version. */
export default function HowItWorks2({}: { alt: string }) {
  const name = useId();
  const [picked, setPicked] = useState(0);
  const change = CHANGES[picked];
  return (
    <>
      <FigureHead tag="Example repository" />
      <fieldset className="m-0 min-w-0 border-0 p-0">
        <legend className="mb-2 text-sm text-ink-2">The request changes only this:</legend>
        <div className="flex flex-wrap gap-2">
          {CHANGES.map((c, i) => (
            <label
              key={c.file}
              className="cursor-pointer rounded-full border border-line px-3 py-0.5 text-sm text-ink-2 hover:border-ink-3 has-checked:border-ink has-checked:bg-ink has-checked:text-panel has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ink"
            >
              <input type="radio" name={name} className="sr-only" checked={picked === i} onChange={() => setPicked(i)} />
              {c.label}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-4 rounded-md border border-line p-2">
        <p className="flex flex-wrap justify-between gap-x-3 px-1.5 pb-1 text-sm text-ink-2">
          <span>booking-assistant, the repository</span>
          <span>Grey files do not count.</span>
        </p>
        <ul role="list" className="list-none pl-0">
          {TREE.map((row) => (
            <Line key={row.path} row={row} touched={row.path === change.file} />
          ))}
        </ul>
      </div>

      <div aria-live="polite" className="mt-3 rounded-md border border-line p-3">
        <p className="flex items-center gap-2 font-bold">
          {change.runs ? (
            <span aria-hidden className="flex gap-1">
              <span className="size-2.5 rounded-full bg-arm-base" />
              <span className="size-2.5 rounded-full bg-arm-cand" />
            </span>
          ) : (
            <LampDot lamp="neutral" className="size-2.5" />
          )}
          {change.runs ? "New version: both run." : "Unchanged: nothing runs."}
        </p>
        <p className="mt-1 text-ink-2">{change.why}</p>
        {change.note && (
          <p className="mt-2 text-sm text-ink-2">
            The comment adds: <span className="text-ink">{change.note}</span>
          </p>
        )}
      </div>
    </>
  );
}
