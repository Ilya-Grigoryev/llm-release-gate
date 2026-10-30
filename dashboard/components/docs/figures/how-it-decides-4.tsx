"use client";

import { useId, useState, type ReactNode } from "react";
import { simulate, type Outcome } from "@/lib/decision-sim";
import { FigureHead, LampDot, type Lamp } from "./kit";

const STEPS = [1, 2, 3, 5, 10, 20, 30, 50];
const DELTA = 5;
const LAMP: Record<Outcome, Lamp> = { pass: "go", block: "stop", "not sure yet": "wait" };
const INK: Record<Outcome, string> = { pass: "var(--go-ink)", block: "var(--stop-ink)", "not sure yet": "var(--wait-ink)" };
const FILL: Record<Outcome, string> = { pass: "var(--go)", block: "var(--stop)", "not sure yet": "var(--wait)" };

const W = 540, LEFT = 16, RIGHT = 16, LO = -50, HI = 30;
const x = (v: number) => LEFT + ((Math.min(HI, Math.max(LO, v)) - LO) / (HI - LO)) * (W - LEFT - RIGHT);

function Switch<T extends string | number | boolean>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex overflow-hidden rounded-md border border-line text-sm">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          tabIndex={value === o.value ? 0 : -1}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
            if (!step) return;
            e.preventDefault();
            const i = options.findIndex((x) => x.value === value);
            const next = options[(i + step + options.length) % options.length];
            onChange(next.value);
            (e.currentTarget.parentElement?.children[options.indexOf(next)] as HTMLElement | undefined)?.focus();
          }}
          className={`px-3 py-1 ${value === o.value ? "bg-ink text-panel" : "hover:bg-paper"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** The planned rule, simulated: more runs narrow the interval until it lies on one side of −δ. */
export default function HowItDecides4() {
  const [step, setStep] = useState(STEPS.indexOf(10));
  const [breaking, setBreaking] = useState(false);
  const [copies, setCopies] = useState(1);
  const [seed, setSeed] = useState(3); // a typical first draw: "not sure yet"
  const id = useId();
  const k = STEPS[step];
  const d = simulate({ k, breaking, copies, seed });
  const cases = 10 * copies;
  const lo = d.half === null ? null : d.diff - d.half;
  const hi = d.half === null ? null : d.diff + d.half;

  return (
    <div>
      <FigureHead tag="Simulation of the planned rule, not the gate's output" />
      <div className="flex flex-wrap items-center gap-3">
        <Switch label="Change" value={breaking} onChange={setBreaking} options={[{ value: false, label: "harmless change" }, { value: true, label: "breaking change" }]} />
        <Switch label="Cases" value={copies} onChange={setCopies} options={[{ value: 1, label: "10 cases" }, { value: 4, label: "40 cases" }]} />
        <button type="button" onClick={() => setSeed((s) => s + 1)} className="rounded-md border border-line px-3 py-1 text-sm hover:border-ink-3">
          Draw again
        </button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label htmlFor={id} className="text-sm text-ink-2">
          Runs per version, K
        </label>
        <input
          id={id}
          type="range"
          min={0}
          max={STEPS.length - 1}
          value={step}
          onChange={(e) => setStep(Number(e.target.value))}
          aria-valuetext={`${k} runs per version`}
          className="w-56 max-w-full accent-[var(--ink)]"
        />
        <output htmlFor={id} className="font-mono text-lg font-bold tabular-nums">
          {k}
        </output>
        <p aria-live="polite" className="ml-auto inline-flex items-center gap-2 font-bold" style={{ color: INK[d.outcome] }}>
          <LampDot lamp={LAMP[d.outcome]} />
          {d.half === null ? `${d.outcome} (today's naive rule)` : d.outcome}
        </p>
      </div>

      <svg viewBox={`0 0 ${W} 132`} className="mt-3 w-full" role="presentation">
        <rect x={x(LO)} y="10" width={x(-DELTA) - x(LO)} height="74" fill="var(--tint-bad)" />
        <text x={x(LO) + 6} y="26" fontSize="13" fill="var(--stop-ink)">
          loss larger than δ
        </text>
        <line x1={x(0)} x2={x(0)} y1="6" y2="88" stroke="var(--ink-3)" strokeWidth="1.5" />
        <line x1={x(-DELTA)} x2={x(-DELTA)} y1="6" y2="88" stroke="var(--ink)" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x={x(-DELTA) + 5} y="100" fontSize="13" fill="var(--ink)" fontWeight="700">
          −δ
        </text>
        {lo !== null && hi !== null && (
          <line x1={x(lo)} x2={x(hi)} y1="50" y2="50" stroke={FILL[d.outcome]} strokeWidth="8" strokeLinecap="round" />
        )}
        <circle cx={x(d.diff)} cy="50" r="7" fill="var(--ink)" stroke="var(--panel)" strokeWidth="2" />
        <g fontSize="12" fill="var(--ink-2)" fontFamily="var(--font-code)">
          {[-50, -40, -30, -20, -10, 0, 10, 20, 30].map((v) => (
            <g key={v}>
              <line x1={x(v)} x2={x(v)} y1="84" y2="90" stroke="var(--ink-3)" />
              <text x={x(v)} y="116" textAnchor="middle">
                {v > 0 ? `+${v}` : v}
              </text>
            </g>
          ))}
        </g>
        <text x={W / 2} y="130" textAnchor="middle" fontSize="12" fill="var(--ink-2)">
          difference in points (candidate − base)
        </text>
      </svg>

      <div className="mt-2 space-y-1 text-sm text-ink-2">
        <p className="font-mono tabular-nums">
          estimate {d.diff >= 0 ? "+" : ""}
          {d.diff.toFixed(1)} points
          {d.half !== null && ` · interval ±${d.half.toFixed(1)}`} · model runs for this decision, if both versions run K times: 2 × {k} × {cases} = {d.runs}
        </p>
        {k === 1 ? (
          <p>One run per version cannot measure noise. The planned rule needs at least two runs per case of the new version.</p>
        ) : (
          k <= 3 && <p>With {k} runs per case the spread is estimated from very few runs, so a single draw can look much narrower than it should.</p>
        )}
        <p>
          δ = 5 points: today&apos;s default, used here for illustration. {copies === 4 && "40 cases: the ten cases repeated. "}
          Assumes both versions run K times; where the base&apos;s runs come from is not decided. The planned rule will use an
          interval that stays valid when runs are added; it will be somewhat wider than this one.
        </p>
      </div>
    </div>
  );
}
