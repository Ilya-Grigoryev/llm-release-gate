"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Link from "next/link";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { CommentCard, LampDot, Tag, type Lamp } from "./kit";

gsap.registerPlugin(useGSAP, ScrollTrigger);

type Outcome = "pass" | "block" | "unchanged";
type Arm = "base" | "cand";
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

/*
 * The scene is drawn on a 720 × 220 grid. Main's rail runs at y = 70 and the request's at y = 160. Ten stations, one per
 * case, stand every 46 units from x = 36, each with a lamp 36 above its rail. The barrier stands on the request's rail and
 * turns about its foot at (540, 196); it lies open along the ground and closes upright across the rail. The signal head
 * sits left of the foot. A train's front is its x; it passes a station when its front reaches the station's x.
 */
const W = 720;
const H = 220;
const RAIL: Record<Arm, number> = { base: 70, cand: 160 };
const R = 11;
const LIFT = 36;
const stationX = (k: number) => 36 + 46 * k;
const PIVOT = { x: 540, y: 196 };
const FROM = -6; // off the left edge
const PAST = 480; // past the last station
const OUT = W + 70; // off the right edge
const STOP = 526; // in front of the closed barrier
const PARKED = 96; // where the trains wait when nothing runs
const RUN = 3.4; // seconds to pass the ten stations
const SPEED = (PAST - FROM) / RUN;
const DWELL = 7; // seconds a decided example stays before the next one plays

const mean = (xs: number[]) => (xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(3) : "–");
const pct = (x: number) => `${(x / W) * 100}%`;

/** A two-car train in its version's colour, front at x = 0, wheels on y = 0. */
function Train({ arm }: { arm: Arm }) {
  const color = `var(--${arm})`;
  return (
    <>
      <rect x="-54" y="-16" width="25" height="11" rx="2" fill={color} />
      <rect x="-50" y="-13.5" width="6.5" height="4" rx="1" fill="var(--panel)" />
      <rect x="-40" y="-13.5" width="6.5" height="4" rx="1" fill="var(--panel)" />
      <path d="M-29.5 -8h4" stroke={color} strokeWidth="2" />
      <path d="M-26 -5V-15q0-3 3-3h14l9 8v5z" fill={color} />
      <rect x="-14" y="-15" width="5" height="4" rx="1" fill="var(--panel)" />
      {[-49, -35, -21, -9].map((x) => (
        <circle key={x} cx={x} cy="-3" r="3" fill="var(--ink)" />
      ))}
    </>
  );
}

/** One version's rail with its sleepers and its ten case lamps, empty until a train passes them. */
function Track({ arm, uid }: { arm: Arm; uid: string }) {
  const y = RAIL[arm];
  const cy = y - LIFT;
  return (
    <g>
      <line x1="0" x2={W} y1={y + 2} y2={y + 2} stroke="var(--ink-3)" strokeOpacity="0.3" strokeWidth="7" strokeDasharray="2 10" />
      <line x1="0" x2={W} y1={y} y2={y} stroke={`var(--${arm})`} strokeOpacity="0.5" strokeWidth="2" />
      {Array.from({ length: 10 }, (_, k) => {
        const cx = stationX(k);
        return (
          <g key={k}>
            <clipPath id={`${uid}-${arm}-${k}`}>
              <circle cx={cx} cy={cy} r={R} />
            </clipPath>
            <line x1={cx} x2={cx} y1={cy + R} y2={y - 1} stroke="var(--line)" strokeWidth="2" />
            <circle cx={cx} cy={cy} r={R} fill="var(--panel)" />
            <rect data-fill={arm} data-k={k} clipPath={`url(#${uid}-${arm}-${k})`} x={cx - R} y={cy + R} width={2 * R} height="0" fill={`var(--${arm})`} />
            <circle data-ring={arm} data-k={k} cx={cx} cy={cy} r={R} fill="none" stroke="var(--line)" strokeWidth="2" />
            {arm === "cand" && <circle data-worse={k} cx={cx} cy={cy} r={R + 4.5} fill="none" stroke="var(--stop)" strokeWidth="2.5" opacity="0" />}
          </g>
        );
      })}
    </g>
  );
}

/** The barrier on the request's rail, open, and the signal head: stop, not sure yet (planned, so never lit), go. */
function Barrier({ uid }: { uid: string }) {
  return (
    <g>
      <defs>
        <pattern id={`${uid}-stripes`} patternUnits="userSpaceOnUse" width="18" height="10">
          <rect width="11" height="10" fill="var(--stop)" />
          <rect x="11" width="7" height="10" fill="var(--panel)" />
        </pattern>
      </defs>
      <rect data-arm x={PIVOT.x} y={PIVOT.y - 4.5} width="80" height="9" rx="3" fill={`url(#${uid}-stripes)`} stroke="var(--stop)" strokeWidth="1.5" />
      <circle cx={PIVOT.x} cy={PIVOT.y} r="7" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
      <rect x="472" y="186" width="58" height="20" rx="10" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
      {(["stop", "wait", "go"] as const).map((lamp, i) => {
        const cx = 484 + i * 17;
        if (lamp === "wait") return <circle key={lamp} cx={cx} cy="196" r="5.5" fill="none" stroke="var(--neutral)" strokeWidth="1.5" strokeDasharray="2.5 2" />;
        return (
          <g key={lamp}>
            <circle data-glow={lamp} cx={cx} cy="196" r="11" fill={`var(--${lamp})`} opacity="0" />
            <circle data-signal={lamp} cx={cx} cy="196" r="6" fill="color-mix(in srgb, var(--neutral) 40%, var(--housing))" />
          </g>
        );
      })}
    </g>
  );
}

/**
 * Four example pull requests through the gate, as two trains: main's and the request's run the same ten cases side by
 * side, lighting each case's lamp to its score. A request that passes rolls on; for one that is blocked, the barrier
 * closes in front of its train. The examples play in turn until the reader picks one or pauses them.
 */
export default function Home1() {
  const [index, setIndex] = useState(0);
  const [run, setRun] = useState(0);
  const [started, setStarted] = useState(false);
  const [decided, setDecided] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
  const [auto, setAuto] = useState(true);
  const [still, setStill] = useState(false);
  const autoplay = useRef(true);
  const first = useRef(true);
  const dwell = useRef<gsap.core.Tween | null>(null);
  const startDwell = useRef<() => void>(() => {});
  const root = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const uid = useId().replace(/[^\w-]/g, "");
  const ex = EXAMPLES[index];
  const ran = ex.cases.length > 0;
  const key = `${index}-${run}`;

  // The first example plays when the scene comes into view.
  useGSAP(
    () => {
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) {
        autoplay.current = false;
        setAuto(false);
        setStill(true);
      }
      ScrollTrigger.create({ trigger: root.current, start: "top 85%", once: true, onEnter: () => setStarted(true) });
    },
    { scope: root },
  );

  useGSAP(
    (_, contextSafe) => {
      if (!started) return;
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const q = gsap.utils.selector(root);
      const tl = gsap.timeline({ delay: first.current && !reduce ? 0.9 : 0.15 });
      first.current = false;

      startDwell.current = contextSafe!(() => {
        if (!autoplay.current || reduce) return;
        dwell.current = gsap.fromTo(
          q("[data-progress]"),
          { scaleX: 0 },
          {
            scaleX: 1,
            duration: DWELL,
            ease: "none",
            onComplete: () => {
              setIndex((i) => (i + 1) % EXAMPLES.length);
              setDecided(false);
              setFocus(null);
            },
          },
        );
      });

      const [base, cand] = [q("[data-train=base]"), q("[data-train=cand]")];
      if (!ran) {
        tl.to([...base, ...cand], { opacity: 0.45, duration: 0.4 });
      } else {
        tl.fromTo([...base, ...cand], { x: FROM }, { x: PAST, duration: RUN, ease: "none" }, 0);
        ex.cases.forEach(([, b, c], k) => {
          const at = (stationX(k) - FROM) / SPEED;
          (["base", "cand"] as const).forEach((arm) => {
            const score = arm === "base" ? b : c;
            const cy = RAIL[arm] - LIFT;
            tl.set(q(`[data-ring=${arm}][data-k="${k}"]`), { attr: { stroke: `var(--${arm})` } }, at);
            tl.to(q(`[data-fill=${arm}][data-k="${k}"]`), { attr: { y: cy + R - 2 * R * score, height: 2 * R * score }, duration: 0.35, ease: "power2.out" }, at);
          });
          tl.call(
            () => {
              q("[data-mean=base]").forEach((el) => (el.textContent = mean(ex.cases.slice(0, k + 1).map((x) => x[1]))));
              q("[data-mean=cand]").forEach((el) => (el.textContent = mean(ex.cases.slice(0, k + 1).map((x) => x[2]))));
            },
            undefined,
            at,
          );
        });
        tl.to(base, { x: OUT, duration: (OUT - PAST) / SPEED, ease: "none" }, RUN);
        if (ex.outcome === "block") {
          tl.to(q("[data-arm]"), { rotation: -90, svgOrigin: `${PIVOT.x} ${PIVOT.y}`, duration: 0.6, ease: "back.out(1.6)" }, RUN - 0.35);
          tl.to(cand, { x: STOP, duration: (3 * (STOP - PAST)) / SPEED, ease: "power3.out" }, RUN);
          tl.to(cand, { x: STOP - 2.5, duration: 0.08, yoyo: true, repeat: 1 }, ">");
        } else {
          tl.to(cand, { x: OUT, duration: (OUT - PAST) / SPEED, ease: "none" }, RUN);
        }
        const lamp = LAMP[ex.outcome];
        tl.set(q(`[data-signal=${lamp}]`), { attr: { fill: `var(--${lamp})` } }, RUN + 0.1);
        tl.fromTo(q(`[data-glow=${lamp}]`), { opacity: 0 }, { opacity: 0.35, duration: 0.25, yoyo: true, repeat: lamp === "stop" ? 4 : 0 }, RUN + 0.1);
        const worse = ex.cases.flatMap(([, b, c], k) => (c < b ? q(`[data-worse="${k}"]`) : []));
        if (worse.length)
          tl.fromTo(worse, { opacity: 0, scale: 0.4, transformOrigin: "50% 50%" }, { opacity: 1, scale: 1, duration: 0.4, ease: "back.out(3)", stagger: 0.08 }, RUN + 0.3);
      }
      tl.call(() => setDecided(true), undefined, ran ? RUN + 0.5 : 0.4);
      tl.call(() => startDwell.current(), undefined, ran ? RUN + 1.6 : 0.6);

      if (reduce) {
        tl.progress(1);
        return;
      }
      ScrollTrigger.create({
        trigger: root.current,
        start: "top bottom",
        end: "bottom top",
        onToggle: (self) => {
          if (self.isActive) {
            tl.resume();
            dwell.current?.resume();
          } else {
            tl.pause();
            dwell.current?.pause();
          }
        },
      });
    },
    { dependencies: [index, run, started], scope: root, revertOnUpdate: true },
  );

  const stopDwell = () => {
    dwell.current?.kill();
    dwell.current = null;
    root.current?.querySelectorAll<HTMLElement>("[data-progress]").forEach((el) => (el.style.transform = "scaleX(0)"));
  };

  const play = (i: number) => {
    autoplay.current = false;
    setAuto(false);
    stopDwell();
    setIndex(i);
    setRun((r) => r + 1);
    setDecided(false);
    setFocus(null);
    setStarted(true);
  };

  const toggleAuto = () => {
    autoplay.current = !autoplay.current;
    setAuto(autoplay.current);
    if (!autoplay.current) stopDwell();
    else if (decided) startDwell.current();
  };

  const onKey = (e: KeyboardEvent, i: number) => {
    const last = EXAMPLES.length - 1;
    const to = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: last }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    const next = (to + EXAMPLES.length) % EXAMPLES.length;
    tabs.current[next]?.focus();
    play(next);
  };

  const shown = focus === null || !ran ? null : ex.cases[focus];
  const label = (arm: Arm) => (
    <span className="leading-tight">
      <span className="block font-bold" style={{ color: `var(--${arm}-ink)` }}>
        {arm === "base" ? "main" : "request"}
      </span>
      <span data-mean={arm} key={key} className="block font-mono text-2xl font-bold tracking-tight tabular-nums">
        –
      </span>
    </span>
  );

  return (
    <div
      ref={root}
      className="overflow-hidden rounded-lg border border-line bg-panel"
      onMouseEnter={() => dwell.current?.pause()}
      onMouseLeave={() => dwell.current?.resume()}
    >
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
              {i === index && (
                <>
                  <span aria-hidden className="absolute inset-x-0 bottom-0 h-0.5 bg-ink min-[900px]:inset-y-0 min-[900px]:right-auto min-[900px]:left-0 min-[900px]:h-auto min-[900px]:w-0.5" />
                  <span aria-hidden data-progress className="absolute inset-x-0 bottom-0 h-0.5 origin-left scale-x-0 bg-ink/35 max-[899px]:hidden" />
                </>
              )}
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
            <div className="flex items-center gap-3">
              <Tag>Example</Tag>
              {!still && (
                <button type="button" onClick={toggleAuto} className="text-sm text-ink-2 underline underline-offset-4 hover:text-ink">
                  {auto ? "Pause the examples" : "Play the examples"}
                </button>
              )}
            </div>
            <p className="min-w-0 text-sm text-ink-2 [overflow-wrap:anywhere]">
              changes <code className="font-mono text-ink">{ex.changes}</code>
            </p>
          </div>

          <p className="mt-5 flex gap-6 sm:hidden">{(["base", "cand"] as const).map((arm) => <span key={arm}>{label(arm)}</span>)}</p>
          <div className="mt-3 grid gap-x-5 sm:mt-6 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
            <div aria-hidden className="relative hidden sm:block">
              {(["base", "cand"] as const).map((arm) => (
                <div key={arm} className="absolute left-0 -translate-y-1/2" style={{ top: `${((RAIL[arm] - LIFT / 2) / H) * 100}%` }}>
                  {label(arm)}
                </div>
              ))}
            </div>
            <div className="relative">
              <svg key={key} aria-hidden viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full">
                <Track arm="base" uid={uid} />
                <Track arm="cand" uid={uid} />
                <Barrier uid={uid} />
                {(["base", "cand"] as const).map((arm) => (
                  <g key={arm} transform={`translate(0 ${RAIL[arm]})`}>
                    <g data-train={arm} transform={`translate(${ran ? FROM : PARKED} 0)`}>
                      <Train arm={arm} />
                    </g>
                  </g>
                ))}
              </svg>
              {ran &&
                ex.cases.map(([id, base, cand], k) => (
                  <button
                    key={`${key}-${id}`}
                    type="button"
                    aria-label={`${id}: main ${base.toFixed(2)}, request ${cand.toFixed(2)}`}
                    onMouseEnter={() => setFocus(k)}
                    onMouseLeave={() => setFocus(null)}
                    onFocus={() => setFocus(k)}
                    onBlur={() => setFocus(null)}
                    onClick={() => setFocus((f) => (f === k ? null : k))}
                    className={`absolute inset-y-0 rounded-md transition-colors ${focus === k ? "bg-ink/[0.07]" : ""}`}
                    style={{ left: pct(stationX(k) - 23), width: pct(46) }}
                  />
                ))}
            </div>
          </div>
          <p className="mt-2 min-h-[3em] text-sm text-ink-2">
            {shown ? (
              <span className="font-mono tabular-nums">
                <span className="text-ink">{shown[0]}</span>
                <span className="mx-2 text-base-ink">main {shown[1].toFixed(2)}</span>
                <span className="text-cand-ink">request {shown[2].toFixed(2)}</span>
              </span>
            ) : ran ? (
              "Each lamp is one case, filled to its score as the train passes. Point at a column to read it. The signal's middle lamp, not sure yet, is planned."
            ) : (
              "Nothing ran: both branches hold the same version of the app."
            )}
          </p>
          <p aria-live="polite" className="sr-only">
            {decided ? `${ex.title}: ${ex.outcome}` : ""}
          </p>

          <div className="mt-4 grid">
            {EXAMPLES.map((e, i) => (
              <div
                key={i}
                aria-hidden={i !== index}
                className={`col-start-1 row-start-1 grid items-start gap-x-6 gap-y-4 transition-[opacity,translate] duration-500 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] ${
                  i !== index ? "invisible opacity-0" : decided ? "opacity-100" : "translate-y-1 opacity-0"
                }`}
              >
                <CommentCard markdown={e.comment} compact />
                <p className="text-ink-2">{e.note}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
