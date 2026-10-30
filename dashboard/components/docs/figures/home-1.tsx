"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { CommentCard, LampDot, Tag, type Lamp } from "./kit";

type Outcome = "pass" | "block" | "unchanged";
type Example = {
  app: string;
  title: string;
  changes: string;
  outcome: Outcome;
  cases: [string, number, number][]; // id, base, candidate
  comment: string;
  note: ReactNode;
};

// Made-up apps; the comments have the exact form the gate writes.
const EXAMPLES: Example[] = [
  {
    app: "Invoice reader",
    title: "Switch to a newer dated model snapshot",
    changes: "configs/invoice.yaml",
    outcome: "pass",
    cases: [
      ["typed-single-page", 1, 1], ["two-pages", 1, 1], ["reverse-charge-vat", 1, 1], ["handwritten-total", 0.75, 0.75],
      ["credit-note", 1, 1], ["foreign-currency", 1, 1], ["faded-scan", 1, 0.75], ["us-date-format", 0.75, 0.75],
      ["discount-line", 1, 1], ["missing-vat-id", 0.75, 0.75],
    ],
    comment: `\`invoice\` · **Release gate: ✅ pass**

Mean score 0.925 → 0.900 (-2.50 points, blocks below -5.00); naive rule: block if the mean drops by more than 5 points.
10 cases, first run of each version · config 1f4a8c02 → 9e6b3d75 · set c4d17a90
Cost of this decision $0.031: base $0.015, candidate $0.016 (successful calls, list prices).

| Case | Base | Candidate |
|---|---|---|
| faded-scan | 1.00 | 0.75 |

[Job log](…)`,
    note: "The model change cost one field on one invoice. A drop of 2.5 points is within the 5 you allow, so the request passes, and the comment still names the case that got worse.",
  },
  {
    app: "Booking assistant",
    title: "Shorten the system prompt",
    changes: "prompts/system.md",
    outcome: "block",
    cases: [
      ["book-meeting-room", 1, 1], ["cancel-for-other-customer", 1, 0], ["book-two-days", 1, 1], ["move-unknown-email", 1, 0],
      ["refund-late-cancel", 0, 0], ["book-past-date", 1, 1], ["ambiguous-booking", 1, 1], ["move-to-free-slot", 1, 1],
      ["refund-over-limit", 0, 0], ["book-for-guest", 1, 0],
    ],
    comment: `\`booking\` · **Release gate: ❌ quality fail**

Mean score 0.800 → 0.500 (-30.00 points, blocks below -5.00); naive rule: block if the mean drops by more than 5 points.
10 cases, first run of each version · config 7d2e91c4 → b03f6a18 · set 52c8e0d7
Cost of this decision $0.127: base $0.068, candidate $0.059 (successful calls, list prices).

| Case | Base | Candidate |
|---|---|---|
| book-for-guest | 1.00 | 0.00 |
| cancel-for-other-customer | 1.00 | 0.00 |
| move-unknown-email | 1.00 | 0.00 |

[Job log](…)`,
    note: (
      <>
        The shorter prompt lost a rule. Three cases ask the assistant to act for someone other than the caller, and an{" "}
        <code className="font-mono text-[0.9em]">order</code> check over the tool calls requires it to look that person up
        first. All three fail. This is the regression the gate is for.
      </>
    ),
  },
  {
    app: "Booking assistant",
    title: "Update the README and the CI workflow",
    changes: "README.md, .github/workflows/ci.yml",
    outcome: "unchanged",
    cases: [],
    comment: `\`booking\` · **Release gate: ⏭ unchanged**

This request does not change \`booking\`: its config, prompts and code hash the same in both branches (\`7d2e91c4a6f0\`), so nothing ran. Documentation, CI, gate.yaml and the paths it ignores do not count.

[Job log](…)`,
    note: "The request touches only documentation and CI, so the booking assistant's version is the same in both branches. Nothing runs and nothing is paid for.",
  },
  {
    app: "Support chat",
    title: "Fix typos in the system prompt",
    changes: "prompts/system.md",
    outcome: "block",
    cases: [
      ["order-status", 1, 1], ["refund-double-charge", 1, 0], ["cancel-after-shipping", 0, 1], ["wrong-size-exchange", 1, 1],
      ["change-delivery-address", 1, 0], ["angry-customer-escalates", 0, 0], ["password-reset", 1, 1], ["invoice-copy", 1, 1],
      ["out-of-policy-refund", 0, 0], ["delivery-delay", 1, 1],
    ],
    comment: `\`support-chat\` · **Release gate: ❌ quality fail**

Mean score 0.700 → 0.600 (-10.00 points, blocks below -5.00); naive rule: block if the mean drops by more than 5 points.
10 cases, first run of each version · config 4c1d9e07 → 8a3f2b65 · set 0e7b5d93
Cost of this decision $0.191: base $0.094, candidate $0.097 (successful calls, list prices).

| Case | Base | Candidate |
|---|---|---|
| change-delivery-address | 1.00 | 0.00 |
| refund-double-charge | 1.00 | 0.00 |

[Job log](…)`,
    note: (
      <>
        Fixing typos was meant to change nothing, yet the score fell by 10 points. In the author&apos;s measurement, one
        unchanged version of a support agent scored between 0.4 and 0.7 on the same 10 cases over 11 runs. A drop like
        this is within what that version did on its own, and one run per version cannot tell it from a real loss.{" "}
        <Link href="/docs/how-it-decides" className="text-ink underline underline-offset-2">
          How it decides
        </Link>{" "}
        shows the measurement.
      </>
    ),
  },
];

const LAMP: Record<Outcome, Lamp> = { pass: "go", block: "stop", unchanged: "neutral" };
const START = 250, STEP = 120, SETTLE = 500;

/** A case lamp, filled from the bottom to the case's score. Dark until its run is in; `worse` rings a drop. */
function CaseLamp({ score, arm, lit, worse = false }: { score: number; arm: "base" | "cand"; lit: boolean; worse?: boolean }) {
  const color = `var(--${arm})`;
  const level = lit ? Math.round(score * 100) : 0;
  const ring = `inset 0 0 0 2px ${lit ? color : "var(--line)"}`;
  return (
    <span
      aria-hidden
      className="relative z-10 block size-[clamp(0.8rem,2.4vw,1.5rem)] rounded-full transition-[box-shadow] duration-300"
      style={{
        background: `linear-gradient(to top, ${color} ${level}%, var(--panel) ${level}%)`,
        boxShadow: worse ? `${ring}, 0 0 0 2.5px var(--panel), 0 0 0 4.5px var(--stop)` : ring,
      }}
    />
  );
}

/*
 * The barrier, drawn on a 128-unit square that lines up with the tracks: they run at y = 24 and 72 (the centres of
 * the two 48-unit rows), the arm stands across both at x = 25 and turns about its foot at y = 96; the signal head
 * hangs under the foot.
 */
const ARM = "transition-transform duration-[900ms] ease-[cubic-bezier(.6,.02,.2,1)]";

function Barrier({ outcome, decided }: { outcome: Outcome; decided: boolean }) {
  const id = useId();
  const open = decided && outcome !== "block";
  const lit = (lamp: Lamp) => decided && LAMP[outcome] === lamp;
  return (
    <svg aria-hidden viewBox="0 0 128 128" className="block size-[5.333rem] overflow-visible sm:size-32">
      <defs>
        <pattern id={`${id}-stripes`} patternUnits="userSpaceOnUse" width="10" height="18">
          <rect width="10" height="11" fill="var(--stop)" />
          <rect y="11" width="10" height="7" fill="var(--panel)" />
        </pattern>
      </defs>
      {[24, 72].map((y, row) => (
        <rect
          key={y}
          x="0"
          y={y - 1}
          width="128"
          height="2"
          fill={row ? "var(--cand)" : "var(--base)"}
          opacity="0.35"
          className={ARM}
          style={{ transformOrigin: "0 0", transform: open ? "scaleX(1)" : "scaleX(0.16)" }}
        />
      ))}
      <g className={ARM} style={{ transformOrigin: "25px 96px", transform: open ? "rotate(90deg)" : "rotate(0deg)" }}>
        <rect x="20" y="2" width="10" height="94" rx="3" fill={`url(#${id}-stripes)`} stroke="var(--stop)" strokeWidth="1.5" />
      </g>
      <circle cx="25" cy="96" r="7.5" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
      <rect x="4" y="106" width="58" height="20" rx="10" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
      {(["stop", "wait", "go"] as const).map((lamp, i) => {
        const cx = 16 + i * 17;
        if (lamp === "wait")
          return <circle key={lamp} cx={cx} cy="116" r="5.5" fill="none" stroke="var(--neutral)" strokeWidth="1.5" strokeDasharray="2.5 2" />;
        return (
          <g key={lamp}>
            <circle cx={cx} cy="116" r="11" fill={`var(--${lamp})`} className="transition-opacity duration-500" opacity={lit(lamp) ? 0.3 : 0} />
            <circle
              cx={cx}
              cy="116"
              r="6"
              className="transition-[fill] duration-300"
              style={{ fill: lit(lamp) ? `var(--${lamp})` : "color-mix(in srgb, var(--neutral) 40%, var(--housing))" }}
            />
          </g>
        );
      })}
    </svg>
  );
}

const mean = (xs: number[]) => (xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(3) : "–");

/** Four example pull requests through the gate: the home page's one orchestrated moment. */
export default function Home1() {
  const [index, setIndex] = useState(0);
  const [lit, setLit] = useState(0);
  const [decided, setDecided] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const timers = useRef<number[]>([]);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const root = useRef<HTMLDivElement>(null);
  const ex = EXAMPLES[index];
  const ran = ex.cases.length > 0;
  const cases = ran ? ex.cases : Array.from({ length: 10 }, (_, k): [string, number, number] => [`case-${k + 1}`, 0, 0]);

  const play = useCallback((i: number) => {
    timers.current.forEach(clearTimeout);
    setIndex(i);
    setFocus(null);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setLit(10);
      setDecided(true);
      return;
    }
    setLit(0);
    setDecided(false);
    timers.current = EXAMPLES[i].cases.length
      ? [
          ...Array.from({ length: 10 }, (_, k) => window.setTimeout(() => setLit(k + 1), START + k * STEP)),
          window.setTimeout(() => setDecided(true), START + 10 * STEP + SETTLE),
        ]
      : [window.setTimeout(() => setDecided(true), START)];
  }, []);

  // Example 1 plays once, when the scene first comes into view.
  useEffect(() => {
    const el = root.current;
    const pending = timers;
    if (!el) return;
    const seen = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        seen.disconnect();
        play(0);
      },
      { threshold: 0.35 },
    );
    seen.observe(el);
    return () => {
      seen.disconnect();
      pending.current.forEach(clearTimeout);
    };
  }, [play]);

  const onKey = (e: KeyboardEvent, i: number) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = (i + step + EXAMPLES.length) % EXAMPLES.length;
    tabs.current[next]?.focus();
    play(next);
  };

  const shown = focus === null || !ran ? null : cases[focus];
  const scored = cases.slice(0, ran ? lit : 0);
  return (
    <div ref={root} className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="grid min-[900px]:grid-cols-[17rem_minmax(0,1fr)]">
        <div
          role="tablist"
          aria-label="Example pull requests"
          aria-orientation="vertical"
          className="flex overflow-x-auto border-b border-line bg-paper/60 min-[900px]:flex-col min-[900px]:border-r min-[900px]:border-b-0"
        >
          {EXAMPLES.map((e, i) => (
            <button
              key={i}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              id={`gate-tab-${i}`}
              role="tab"
              type="button"
              aria-selected={i === index}
              aria-controls="gate-panel"
              tabIndex={i === index ? 0 : -1}
              onClick={() => play(i)}
              onKeyDown={(ev) => onKey(ev, i)}
              className={`group relative w-56 shrink-0 border-line px-4 py-3.5 text-left max-[899px]:border-r min-[900px]:w-auto min-[900px]:border-b ${
                i === index ? "bg-panel" : "hover:bg-panel"
              }`}
            >
              {i === index && <span aria-hidden className="absolute inset-x-0 bottom-0 h-0.5 bg-ink min-[900px]:inset-y-0 min-[900px]:right-auto min-[900px]:left-0 min-[900px]:h-auto min-[900px]:w-0.5" />}
              <span className="block text-sm text-ink-2">{e.app}</span>
              <span className="mt-0.5 block leading-snug font-bold text-balance">{e.title}</span>
              <span className="mt-1.5 flex items-center gap-1.5 text-sm text-ink-2">
                <LampDot lamp={LAMP[e.outcome]} className="size-2" />
                {e.outcome}
              </span>
            </button>
          ))}
        </div>

        <div id="gate-panel" role="tabpanel" aria-labelledby={`gate-tab-${index}`} className="min-w-0 p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <Tag>Example</Tag>
            <p className="min-w-0 text-sm text-ink-2 [overflow-wrap:anywhere]">
              changes <code className="font-mono text-ink">{ex.changes}</code>
            </p>
          </div>

          <p className="mt-5 flex gap-5 text-sm sm:hidden">
            {(["base", "cand"] as const).map((arm, row) => (
              <span key={arm}>
                <span className="font-bold" style={{ color: `var(--${arm}-ink)` }}>
                  {row ? "request" : "main"}
                </span>{" "}
                <span className="font-mono font-bold tabular-nums">{mean(scored.map((c) => (row ? c[2] : c[1])))}</span>
              </span>
            ))}
          </p>
          <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] grid-rows-[2rem_2rem_auto] items-center gap-x-2.5 sm:mt-6 sm:grid-cols-[auto_auto_minmax(0,1fr)_auto] sm:grid-rows-[3rem_3rem_auto] sm:gap-x-5">
            {(["base", "cand"] as const).map((arm, row) => {
              const value = mean(scored.map((c) => (row ? c[2] : c[1])));
              return (
                <div key={arm} className="contents">
                  <span className={`col-start-1 hidden leading-tight sm:block ${row ? "row-start-2" : "row-start-1"}`}>
                    <span className="block font-bold" style={{ color: `var(--${arm}-ink)` }}>
                      {row ? "request" : "main"}
                    </span>
                    <span className="block text-sm text-ink-3">{row ? "candidate" : "base"}</span>
                  </span>
                  <span className={`col-start-2 hidden text-right font-mono text-2xl font-bold tracking-tight tabular-nums sm:block ${row ? "row-start-2" : "row-start-1"}`}>
                    {value}
                  </span>
                </div>
              );
            })}
            <div className="relative col-start-1 row-span-2 row-start-1 flex h-full sm:col-start-3">
              {[25, 75].map((top) => (
                <span key={top} aria-hidden className="absolute left-0 -right-2.5 h-0.5 -translate-y-1/2 sm:-right-5" style={{ top: `${top}%`, background: top < 50 ? "var(--base)" : "var(--cand)", opacity: 0.35 }} />
              ))}
              {cases.map(([id, base, cand], k) => (
                <button
                  key={`${index}-${id}`}
                  type="button"
                  disabled={!ran}
                  aria-label={ran ? `${id}: main ${base.toFixed(2)}, request ${cand.toFixed(2)}` : undefined}
                  onMouseEnter={() => setFocus(k)}
                  onMouseLeave={() => setFocus(null)}
                  onFocus={() => setFocus(k)}
                  onBlur={() => setFocus(null)}
                  onClick={() => setFocus((f) => (f === k ? null : k))}
                  className={`grid flex-1 grid-rows-2 place-items-center rounded-full transition-colors ${focus === k ? "bg-ink/[0.07]" : ""}`}
                >
                  <CaseLamp score={base} arm="base" lit={ran && k < lit} />
                  <CaseLamp score={cand} arm="cand" lit={ran && k < lit} worse={decided && cand < base} />
                </button>
              ))}
            </div>
            <div className="col-start-2 row-span-3 row-start-1 self-start sm:col-start-4">
              <Barrier outcome={ex.outcome} decided={decided} />
            </div>
            <p className="col-start-1 row-start-3 pt-2 text-sm text-ink-2 sm:col-span-3">
              {shown ? (
                <span className="font-mono tabular-nums">
                  <span className="text-ink">{shown[0]}</span>
                  <span className="mx-2 text-base-ink">main {shown[1].toFixed(2)}</span>
                  <span className="text-cand-ink">request {shown[2].toFixed(2)}</span>
                </span>
              ) : ran ? (
                "Each lamp is one case, filled to its score. Point at a column to read it. The barrier's middle lamp, not sure yet, is planned."
              ) : (
                "Nothing ran: both branches hold the same version of the app."
              )}
            </p>
          </div>
          <p aria-live="polite" className="sr-only">
            {decided ? `${ex.title}: ${ex.outcome}` : ""}
          </p>

          <div className={`mt-5 grid gap-x-6 gap-y-4 transition-[opacity,translate] duration-500 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] ${decided ? "opacity-100" : "translate-y-1 opacity-0"}`}>
            <CommentCard markdown={ex.comment} compact />
            <div className="space-y-3 text-ink-2">
              <p>{ex.note}</p>
              {ran && (
                <p className="text-sm">
                  <code className="font-mono">config … → … · set …</code> in the comment are the ids of the two versions (config,
                  prompts and code) and of the test set.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
