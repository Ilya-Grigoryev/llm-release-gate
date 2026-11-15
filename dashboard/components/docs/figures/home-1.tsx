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
Checks: with 1 + 1 runs no break can be significant; a single broken check can block from 4 runs of each version (one-sided Fisher, α 0.025). 1 of 40 passed less often.
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
Checks: with 1 + 1 runs no break can be significant; a single broken check can block from 4 runs of each version (one-sided Fisher, α 0.025). 3 of 30 passed less often.
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
Checks: with 1 + 1 runs no break can be significant; a single broken check can block from 4 runs of each version (one-sided Fisher, α 0.025). 2 of 20 passed less often.
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
 * The scene is drawn on a 760 × 220 grid. Main's rail runs at y = 70 and the request's at y = 160; from x = 590 both
 * bend into one rail at y = 115. Ten stations, one per case, stand every 46 units from x = 36, each with a lamp 36 above
 * its rail. Each rail has a barrier at x = 548 with its foot on the outer side: it lies open along the ground and turns
 * across the rail to close. A train's position is the distance of its front along its route, counted so that it equals
 * x on the straight part.
 */
const W = 760;
const H = 220;
const RAIL: Record<Arm, number> = { base: 70, cand: 160 };
const BEND = 590;
const JOIN = { x: 670, y: 115 };
const R = 11;
const LIFT = 36;
const stationX = (k: number) => 36 + 46 * k;
const GATE = 548;
const FOOT: Record<Arm, number> = { base: 40, cand: 196 }; // y of each barrier's foot
const LEAD = 150; // routes start this far left of the scene
const curve = (arm: Arm) => `C${BEND + 40} ${RAIL[arm]} ${JOIN.x - 40} ${JOIN.y} ${JOIN.x} ${JOIN.y}`;
const rail = (arm: Arm) => `M0 ${RAIL[arm]}H${BEND}${curve(arm)}`;
const route = (arm: Arm) => `M${-LEAD} ${RAIL[arm]}H${BEND}${curve(arm)}H${W + 260}`;
const CARS = [13, 41, 67, 93]; // from a train's front to the middle of each car: the engine, then three coaches
const FROM = -10; // off the left edge
const PAST = 470; // past the last station
const STOP = 532; // in front of a closed barrier
const PARKED = 150; // where the trains wait when nothing runs
const RUN = 1.8; // seconds to pass the ten stations
const SPEED = (PAST - FROM) / RUN;
const DWELL = 7; // seconds a decided example stays before the next one plays

const mean = (xs: number[]) => (xs.length ? (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(3) : "–");
const pct = (x: number) => `${(x / W) * 100}%`;

/** Puts each car of a train on its route, turned along it, for the train's front at `front`. */
function place(path: SVGPathElement, cars: Element[], front: number) {
  const total = path.getTotalLength();
  cars.forEach((car, i) => {
    const s = Math.min(total, Math.max(0, front + LEAD - CARS[i]));
    const p = path.getPointAtLength(s);
    const n = path.getPointAtLength(Math.min(total, s + 1));
    car.setAttribute("transform", `translate(${p.x} ${p.y}) rotate(${(Math.atan2(n.y - p.y, n.x - p.x) * 180) / Math.PI})`);
  });
}

/** An engine and three coaches in the version's colour, standing with the front at `at` on the straight part. */
function Train({ arm, at }: { arm: Arm; at: number }) {
  const color = `var(--${arm})`;
  return CARS.map((back, i) => (
    <g key={i} data-car={arm} transform={`translate(${at - back} ${RAIL[arm]})`}>
      {i === 0 ? (
        <>
          <path d="M-13 -5V-15q0-3 3-3h15l8 8v5z" fill={color} />
          <rect x="-1" y="-15" width="5" height="4" rx="1" fill="var(--panel)" />
        </>
      ) : (
        <>
          <rect x="-11" y="-16" width="22" height="11" rx="2" fill={color} />
          <rect x="-8" y="-13.5" width="6.5" height="4" rx="1" fill="var(--panel)" />
          <rect x="1.5" y="-13.5" width="6.5" height="4" rx="1" fill="var(--panel)" />
          <path d="M11 -8h4" stroke={color} strokeWidth="2" />
        </>
      )}
      {(i === 0 ? [-8, 5] : [-6, 6]).map((x) => (
        <circle key={x} cx={x} cy="-3" r="3" fill="var(--ink)" />
      ))}
    </g>
  ));
}

/** The gate's comment while both versions run: the note `comment --running` posts, before the verdict replaces it. */
function Pending({ ex }: { ex: Example }) {
  const name = ex.comment.match(/^`([^`]+)`/)?.[1];
  const n = ex.cases.length;
  return (
    <CommentCard compact>
      <p>
        <code className="rounded-sm bg-ink/[0.06] px-1 font-mono text-[0.9em]">{name}</code> ·{" "}
        <strong>Release gate: ⏳ running</strong>
      </p>
      <p>
        Started 2026-11-15 14:40 UTC: the gate compares the target branch&apos;s version with this request&apos;s
        {n ? ` on ${n} cases` : ""}. The verdict replaces this note; if the job stops early (cancelled, timed out), the
        note stays: see the job log.
      </p>
      <p>
        <span className="text-arm-base underline underline-offset-2">Job log</span>
      </p>
      <div aria-hidden className="space-y-2 pt-1">
        {["w-11/12", "w-3/4", "w-1/2"].map((w) => (
          <div key={w} className={`h-2.5 rounded-full bg-line motion-safe:animate-pulse ${w}`} />
        ))}
      </div>
    </CommentCard>
  );
}

/** Sleepers and a rail along a path. */
function Rail({ d, color }: { d: string; color: string }) {
  return (
    <>
      <path d={d} transform="translate(0 2)" fill="none" stroke="var(--ink-3)" strokeOpacity="0.3" strokeWidth="7" strokeDasharray="2 10" />
      <path d={d} fill="none" stroke={color} strokeOpacity="0.5" strokeWidth="2" />
    </>
  );
}

/** One version's rail up to the bend and its ten case lamps, empty until a train passes them. */
function Track({ arm, uid }: { arm: Arm; uid: string }) {
  const y = RAIL[arm];
  const cy = y - LIFT;
  return (
    <g>
      <Rail d={rail(arm)} color={`var(--${arm})`} />
      <path data-route={arm} d={route(arm)} fill="none" stroke="none" />
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

/** The two barriers, open, and the signal head at the join: stop, not sure yet (never lit: the examples use the naive rule), go. */
function Barriers({ uid }: { uid: string }) {
  return (
    <g>
      <defs>
        <pattern id={`${uid}-stripes`} patternUnits="userSpaceOnUse" width="18" height="10">
          <rect width="11" height="10" fill="var(--stop)" />
          <rect x="11" width="7" height="10" fill="var(--panel)" />
        </pattern>
      </defs>
      {(["base", "cand"] as const).map((arm) => (
        <g key={arm}>
          <rect data-arm={arm} x={GATE - 80} y={FOOT[arm] - 4.5} width="80" height="9" rx="3" fill={`url(#${uid}-stripes)`} stroke="var(--stop)" strokeWidth="1.5" />
          <circle cx={GATE} cy={FOOT[arm]} r="7" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
        </g>
      ))}
      <rect x="690" y="136" width="58" height="20" rx="10" fill="var(--housing)" stroke="var(--neutral)" strokeOpacity="0.4" />
      {(["stop", "wait", "go"] as const).map((lamp, i) => {
        const cx = 702 + i * 17;
        if (lamp === "wait") return <circle key={lamp} cx={cx} cy="146" r="5.5" fill="none" stroke="var(--neutral)" strokeWidth="1.5" strokeDasharray="2.5 2" />;
        return (
          <g key={lamp}>
            <circle data-glow={lamp} cx={cx} cy="146" r="11" fill={`var(--${lamp})`} opacity="0" />
            <circle data-signal={lamp} cx={cx} cy="146" r="6" fill="color-mix(in srgb, var(--neutral) 40%, var(--housing))" />
          </g>
        );
      })}
    </g>
  );
}

/**
 * Four example pull requests through the gate, as two trains: main's and the request's run the same ten cases side by
 * side, lighting each case's lamp to its score, and then their rails join into one. A request that passes takes the
 * joined rail and a barrier stops main's train; for a request that is blocked, it is the other way round. The gate's
 * comment shows from the start, as a placeholder while the trains run, and becomes the report once they are decided. The
 * examples play in turn until the reader picks one.
 */
export default function Home1() {
  const [index, setIndex] = useState(0);
  const [run, setRun] = useState(0);
  const [started, setStarted] = useState(false);
  const [decided, setDecided] = useState(false);
  const [focus, setFocus] = useState<number | null>(null);
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
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) autoplay.current = false;
      ScrollTrigger.create({ trigger: root.current, start: "top 85%", once: true, onEnter: () => setStarted(true) });
    },
    { scope: root },
  );

  useGSAP(
    (_, contextSafe) => {
      if (!started) return;
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const q = gsap.utils.selector(root);
      const tl = gsap.timeline({ delay: first.current && !reduce ? 0.3 : 0.15 });
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

      const cars = { base: q("[data-car=base]"), cand: q("[data-car=cand]") };
      if (!ran) {
        tl.to([...cars.base, ...cars.cand], { opacity: 0.45, duration: 0.4 });
      } else {
        const routeOf = (arm: Arm) => root.current!.querySelector<SVGPathElement>(`[data-route=${arm}]`)!;
        const path = { base: routeOf("base"), cand: routeOf("cand") };
        const at = { base: { x: FROM }, cand: { x: FROM } };
        const move = (arm: Arm) => () => place(path[arm], cars[arm], at[arm].x);
        tl.to(at.base, { x: PAST, duration: RUN, ease: "none", onUpdate: move("base") }, 0);
        tl.to(at.cand, { x: PAST, duration: RUN, ease: "none", onUpdate: move("cand") }, 0);
        ex.cases.forEach(([, b, c], k) => {
          const t = (stationX(k) - FROM) / SPEED;
          (["base", "cand"] as const).forEach((arm) => {
            const score = arm === "base" ? b : c;
            const cy = RAIL[arm] - LIFT;
            tl.set(q(`[data-ring=${arm}][data-k="${k}"]`), { attr: { stroke: `var(--${arm})` } }, t);
            tl.to(q(`[data-fill=${arm}][data-k="${k}"]`), { attr: { y: cy + R - 2 * R * score, height: 2 * R * score }, duration: 0.3, ease: "power2.out" }, t);
          });
          tl.call(
            () => {
              q("[data-mean=base]").forEach((el) => (el.textContent = mean(ex.cases.slice(0, k + 1).map((x) => x[1]))));
              q("[data-mean=cand]").forEach((el) => (el.textContent = mean(ex.cases.slice(0, k + 1).map((x) => x[2]))));
            },
            undefined,
            t,
          );
        });
        // The request takes the joined rail when it passes; otherwise main keeps it.
        const winner: Arm = ex.outcome === "pass" ? "cand" : "base";
        const loser: Arm = winner === "cand" ? "base" : "cand";
        const end = path[winner].getTotalLength() - LEAD;
        tl.to(at[winner], { x: end, duration: (end - PAST) / SPEED, ease: "none", onUpdate: move(winner) }, RUN);
        tl.to(q(`[data-arm=${loser}]`), { rotation: loser === "base" ? -90 : 90, svgOrigin: `${GATE} ${FOOT[loser]}`, duration: 0.4, ease: "back.out(1.6)" }, RUN);
        tl.to(at[loser], { x: STOP, duration: (3 * (STOP - PAST)) / SPEED, ease: "power3.out", onUpdate: move(loser) }, RUN);
        tl.to(at[loser], { x: STOP - 2.5, duration: 0.08, yoyo: true, repeat: 1, onUpdate: move(loser) }, ">");
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
    stopDwell();
    setIndex(i);
    setRun((r) => r + 1);
    setDecided(false);
    setFocus(null);
    setStarted(true);
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
              className={`group relative w-56 shrink-0 cursor-pointer border-line px-4 py-3.5 text-left max-[899px]:border-r min-[900px]:w-auto min-[900px]:border-b ${
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
            <Tag>Example</Tag>
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
                <Rail d={`M${JOIN.x} ${JOIN.y}H${W}`} color="var(--ink-3)" />
                <Track arm="base" uid={uid} />
                <Track arm="cand" uid={uid} />
                <Barriers uid={uid} />
                <Train arm="base" at={ran ? FROM : PARKED} />
                <Train arm="cand" at={ran ? FROM : PARKED} />
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
              "Each lamp is one case, filled to its score as the train passes. Point at a column to read it. The signal's middle lamp, not sure yet, stays dark under the naive rule these examples use."
            ) : (
              "Nothing ran: both branches hold the same version of the app."
            )}
          </p>
          <p aria-live="polite" className="sr-only">
            {decided ? `${ex.title}: ${ex.outcome}` : ""}
          </p>

          {/* Every example's report and note sit in one cell, hidden but for the current one, so the height never jumps. */}
          <div className="mt-4 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <div className="grid">
              {EXAMPLES.map((e, i) => (
                <div key={i} aria-hidden className="invisible col-start-1 row-start-1">
                  <CommentCard markdown={e.comment} compact />
                </div>
              ))}
              {decided ? (
                <div key={`report-${key}`} className="col-start-1 row-start-1 rounded-md motion-safe:animate-[comment-edit_1.4s_ease-out]">
                  <CommentCard markdown={ex.comment} compact edited />
                </div>
              ) : (
                <div key={`pending-${key}`} className="col-start-1 row-start-1">
                  <Pending ex={ex} />
                </div>
              )}
            </div>
            <div className="grid max-lg:order-first">
              {EXAMPLES.map((e, i) => (
                <p key={i} aria-hidden={i !== index} className={`col-start-1 row-start-1 text-ink-2 ${i !== index ? "invisible" : ""}`}>
                  {e.note}
                </p>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
