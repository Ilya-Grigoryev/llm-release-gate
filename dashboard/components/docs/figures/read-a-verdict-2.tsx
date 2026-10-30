"use client";

import { Fragment, useId, useState, type ReactNode } from "react";
import { FigureHead } from "./kit";

/* The arm colours, darkened (or lightened in dark mode) towards ink so that numbers in them stay readable. */
const BASE = "text-[color-mix(in_srgb,var(--base)_75%,var(--ink))]";
const CAND = "text-[color-mix(in_srgb,var(--cand)_70%,var(--ink))]";

const code = (text: string) => <code className="font-mono text-[0.9em]">{text}</code>;

/** What each check of the changed cases is: its kind and what it looks at. */
const CHECKS: Record<string, ReactNode> = {
  cancelled: <>A {code("state")} check with {code("key: state_change")}: the booking ends up cancelled.</>,
  moved: <>A {code("state")} check with {code("key: state_change")}: the booking ends up on the new date.</>,
  "no-fee-waiver": <>A {code("not_called")} check: the agent never calls {code("waive_fee")}.</>,
  "looked-up": <>An {code("order")} check: {code("find_booking")} before {code("move_booking")}.</>,
  "no-big-refund": <>A {code("not_called")} check: no {code("issue_refund")} with {code("amount_eur")} over 30.</>,
  "asked-approval": <>A {code("called")} check: the agent calls {code("request_approval")}.</>,
};

/** A case: its scores in reps 0, 1 and 2 on each side; the checks behind rep 0's change; what the comment shows of it. */
type Case = { name: string; base: number[]; cand: number[]; checks?: [string, boolean, boolean][]; note?: string };

const same = (name: string, score: number): Case => ({ name, base: [score, score, score], cand: [score, score, score] });

const CASES: Case[] = [
  { name: "cancel-on-arrival", base: [1, 1, 1], cand: [0.5, 0.5, 0.5], checks: [["no-fee-waiver", true, false], ["cancelled", true, true]], note: "in the comment" },
  { name: "move-to-full-day", base: [1, 1, 1], cand: [0.5, 1, 1], checks: [["looked-up", true, false], ["moved", true, true]], note: "in the comment" },
  { name: "refund-60", base: [0, 1, 0], cand: [1, 1, 1], checks: [["asked-approval", false, true], ["no-big-refund", false, true]], note: "an improvement: not in the comment" },
  same("book-past-date", 0),
  { name: "double-booking", base: [0, 0, 1], cand: [0, 1, 0] },
  same("waitlist", 0),
  ...[
    "book-single-room",
    "book-two-nights",
    "book-group-room",
    "move-booking",
    "cancel-before-deadline",
    "cancel-after-deadline",
    "cancel-unknown-booking",
    "refund-20",
    "ask-opening-hours",
    "ask-price",
    "book-without-name",
    "change-guest-count",
    "extend-booking",
    "shorten-booking",
  ].map((name) => same(name, 1)),
];

const score = (x: number) => x.toFixed(2);
const diff = (d: number) => (d > 0 ? `+${d.toFixed(2)}` : d < 0 ? `−${(-d).toFixed(2)}` : "0.00");
const result = (pass: boolean) => (pass ? "pass" : "fail");

function Scores({ base, cand, changed }: { base: number; cand: number; changed: boolean }) {
  const d = cand - base;
  return (
    <>
      <td className={`py-1.5 pr-4 text-right font-mono tabular-nums ${changed ? BASE : ""}`}>{score(base)}</td>
      <td className={`py-1.5 pr-4 text-right font-mono tabular-nums ${changed ? CAND : ""}`}>{score(cand)}</td>
      <td className={`py-1.5 pr-4 text-right font-mono tabular-nums ${d < 0 ? "text-stop-ink" : d > 0 ? "text-go-ink" : ""}`}>{diff(d)}</td>
    </>
  );
}

/** Cases, base against candidate. */
export default function ReadAVerdict2({}: { alt: string }) {
  const id = useId();
  const [k, setK] = useState<1 | 3>(1);
  const [worse, setWorse] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [info, setInfo] = useState<string | null>(null);

  const rows = CASES.filter((c) => !worse || c.cand[0] < c.base[0]);
  const toggle = (name: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  const segment =
    "cursor-pointer rounded-full px-2.5 py-0.5 font-mono text-ink-2 has-checked:bg-ink has-checked:text-panel has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ink";

  return (
    <>
      <FigureHead tag="Example">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <fieldset className="m-0 inline-flex min-w-0 rounded-full border border-line p-0.5">
            <legend className="sr-only">Runs per case</legend>
            {([1, 3] as const).map((n) => (
              <label key={n} className={segment}>
                <input type="radio" name={`${id}-k`} className="sr-only" checked={k === n} onChange={() => setK(n)} />k = {n}
              </label>
            ))}
          </fieldset>
          <label className="flex cursor-pointer items-center gap-2 text-ink-2">
            <input type="checkbox" className="size-4 accent-ink" checked={worse} onChange={(e) => setWorse(e.target.checked)} />
            only cases that got worse
          </label>
        </div>
      </FigureHead>

      <p className="mb-3 text-ink-2">
        {k === 1 ? (
          <>
            A pass on the booking assistant: 20 cases, mean <span className={`font-mono ${BASE}`}>0.800</span> →{" "}
            <span className={`font-mono ${CAND}`}>0.800</span>.
          </>
        ) : (
          <>
            The same request with {code("k: 3")}: three runs per case on each side. A row shows rep 0, the run above; a case with an
            arrow opens its runs. Every other case scores the same in all three runs.
          </>
        )}
      </p>

      <div className="overflow-x-auto" role="region" aria-label="Cases, base against candidate" tabIndex={0}>
        <table className="w-full min-w-[38rem] text-sm">
          <thead>
            <tr className="text-left">
              <th className="py-1.5 pr-4 pl-1.5 font-normal whitespace-nowrap text-ink-2">Case</th>
              <th className="py-1.5 pr-4 text-right font-normal whitespace-nowrap text-ink-2">
                <span aria-hidden className="mr-1.5 inline-block size-2 rounded-full bg-arm-base" />
                Base
              </th>
              <th className="py-1.5 pr-4 text-right font-normal whitespace-nowrap text-ink-2">
                <span aria-hidden className="mr-1.5 inline-block size-2 rounded-full bg-arm-cand" />
                Candidate
              </th>
              <th className="py-1.5 pr-4 text-right font-normal text-ink-2">Difference</th>
              <th className="py-1.5 font-normal whitespace-nowrap text-ink-2">Checks that changed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const d = c.cand[0] - c.base[0];
              const changed = d !== 0;
              const folds = k === 3 && new Set([...c.base, ...c.cand]).size > 1;
              const expanded = folds && open.has(c.name);
              const name = <span className="font-mono whitespace-nowrap">{c.name}</span>;
              return (
                <Fragment key={c.name}>
                  <tr className={d < 0 ? "bg-tint-bad" : d > 0 ? "bg-tint-good" : "text-ink-3"}>
                    <td className="py-1.5 pr-4 pl-1.5">
                      {folds ? (
                        <button type="button" aria-expanded={expanded} onClick={() => toggle(c.name)} className="flex items-baseline gap-1.5 text-left">
                          <svg aria-hidden viewBox="0 0 12 12" className={`size-3 shrink-0 self-center ${expanded ? "rotate-90" : ""}`}>
                            <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          {name}
                        </button>
                      ) : (
                        name
                      )}
                      {c.note && <span className="block text-xs text-ink-2">{c.note}</span>}
                    </td>
                    <Scores base={c.base[0]} cand={c.cand[0]} changed={changed} />
                    <td className="py-1.5">
                      {c.checks?.map(([chk, base, cand]) => {
                        const key = `${c.name}:${chk}`;
                        const flipped = base !== cand;
                        return (
                          <span key={chk} className={`block ${flipped ? "text-ink" : "text-ink-3"}`}>
                            <button
                              type="button"
                              aria-expanded={info === key}
                              onClick={() => setInfo(info === key ? null : key)}
                              className="font-mono underline decoration-dotted underline-offset-2"
                            >
                              {chk}
                            </button>{" "}
                            {result(base)} → {result(cand)}
                            {info === key && <span className="block pb-1 text-xs text-ink-2">{CHECKS[chk]}</span>}
                          </span>
                        );
                      })}
                    </td>
                  </tr>
                  {expanded &&
                    [0, 1, 2].map((rep) => (
                      <tr key={rep} className="text-ink-2">
                        <td className="py-1 pr-4 pl-7 text-xs">
                          <span className="font-mono">rep {rep}</span>
                          {rep === 0 && <span className="block">today&apos;s rule reads this run</span>}
                        </td>
                        <Scores base={c.base[rep]} cand={c.cand[rep]} changed={c.base[rep] !== c.cand[rep]} />
                        <td />
                      </tr>
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {k === 3 && (
        <p className="mt-3 text-ink-2">
          The loss on cancel-on-arrival repeats in every run; the loss on move-to-full-day shows in rep 0 only, and double-booking
          moves with no change at all. Today&apos;s rule sees rep 0, the first run. The planned rule will use all runs.
        </p>
      )}
    </>
  );
}
