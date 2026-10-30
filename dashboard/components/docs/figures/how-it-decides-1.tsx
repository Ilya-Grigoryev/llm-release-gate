"use client";

import { useEffect, useRef, useState } from "react";
import { FigureHead } from "./kit";

// The author's measurement: one support agent, nothing in it changed, 10 pass-or-fail cases, 11 runs (case 1 first).
const RUNS = [
  { day: "25 Oct", cases: "1110101110" },
  { day: "25 Oct", cases: "1110101100" },
  { day: "25 Oct", cases: "1110001011" },
  { day: "25 Oct", cases: "1111101001" },
  { day: "25 Oct", cases: "1111010000" },
  { day: "25 Oct", cases: "1111010010" },
  { day: "25 Oct", cases: "1111010001" },
  { day: "25 Oct", cases: "1100010001" },
  { day: "26 Oct", cases: "1111101100" },
  { day: "26 Oct", cases: "1111110010" },
  { day: "26 Oct", cases: "1111100100" },
].map((r) => ({ ...r, passed: [...r.cases].filter((c) => c === "1").length }));

const W = 540, LEFT = 52, RIGHT = 118, TOP = 12, PANEL = 150, LAMPS = 214, ROW = 13;
const CELL = (W - LEFT - RIGHT) / RUNS.length;
const x = (i: number) => LEFT + (i + 0.5) * CELL;
const y = (v: number) => TOP + ((0.8 - v) / 0.5) * PANEL;
const H = LAMPS + 9 * ROW + 14;

export default function HowItDecides1() {
  const [shown, setShown] = useState(RUNS.length); // complete at rest; the animation starts when the figure is seen
  const [focus, setFocus] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);

  const play = () => {
    timers.current.forEach(clearTimeout);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return setShown(RUNS.length);
    setShown(0);
    timers.current = RUNS.map((_, i) => window.setTimeout(() => setShown(i + 1), 250 + i * 150));
  };

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const seen = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        seen.disconnect();
        play();
      }
    }, { threshold: 0.4 });
    seen.observe(el);
    const pending = timers.current;
    return () => {
      seen.disconnect();
      pending.forEach(clearTimeout);
    };
  }, []);

  const r = focus === null ? null : RUNS[focus];
  return (
    <div ref={ref}>
      <FigureHead tag="The author's measurement on a support agent">
        <button type="button" onClick={play} className="rounded-md border border-line px-3 py-1 text-sm hover:border-ink-3">
          Replay
        </button>
      </FigureHead>
      <p aria-live="polite" className="mb-2 min-h-6 font-mono text-sm text-ink-2 tabular-nums">
        {r ? `Run ${focus! + 1} · ${r.day} · mean ${(r.passed / 10).toFixed(2)} · ${r.passed} of 10 cases passed` : "Point at a run, or tab to it, to read it."}
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="group" aria-label="Mean score and passed cases of each run">
        <g fontSize="13" fill="var(--ink-2)">
          {[0.4, 0.5, 0.6, 0.7].map((v) => (
            <g key={v}>
              <line x1={LEFT} x2={W - RIGHT} y1={y(v)} y2={y(v)} stroke="var(--line)" />
              <text x={LEFT - 8} y={y(v) + 4} textAnchor="end" fontFamily="var(--font-code)">
                {v.toFixed(2)}
              </text>
            </g>
          ))}
          <text x={LEFT - 8} y={TOP + 4} textAnchor="end">mean</text>
        </g>

        {/* the range the unchanged agent covered, and today's delta for scale */}
        <g style={{ opacity: shown === RUNS.length ? 1 : 0, transition: "opacity 400ms" }} fill="var(--ink-2)" fontSize="13">
          <path d={`M${W - RIGHT + 8} ${y(0.7)}h6V${y(0.4)}h-6`} fill="none" stroke="var(--ink)" strokeWidth="1.5" />
          <text x={W - RIGHT + 20} y={(y(0.7) + y(0.4)) / 2 - 2} fill="var(--ink)" fontWeight="700">30 points</text>
          <text x={W - RIGHT + 20} y={(y(0.7) + y(0.4)) / 2 + 14}>no change</text>
          <rect x={W - RIGHT + 20} y={y(0.7)} width="6" height={y(0.65) - y(0.7)} fill="var(--ink)" />
          <text x={W - RIGHT + 32} y={(y(0.7) + y(0.65)) / 2 + 4} fontSize="12">δ = 5 points</text>
        </g>

        {RUNS.map((run, i) => {
          const on = i < shown;
          return (
            <g
              key={i}
              tabIndex={0}
              role="img"
              aria-label={`Run ${i + 1}, ${run.day}: mean ${(run.passed / 10).toFixed(2)}, ${run.passed} of 10 cases passed`}
              onMouseEnter={() => setFocus(i)}
              onMouseLeave={() => setFocus(null)}
              onFocus={() => setFocus(i)}
              onBlur={() => setFocus(null)}
              className="cursor-default outline-none"
            >
              <rect x={x(i) - CELL / 2} y={TOP - 6} width={CELL} height={H - TOP} fill={focus === i ? "var(--paper)" : "transparent"} />
              <circle
                cx={x(i)}
                cy={y(run.passed / 10)}
                r="7"
                fill="var(--base)"
                style={{ opacity: on ? 1 : 0, transform: on ? "none" : "translateY(-24px)", transition: "opacity 250ms, transform 250ms ease-out" }}
              />
              <text x={x(i)} y={TOP + PANEL + 22} textAnchor="middle" fontSize="13" fill="var(--ink-2)" fontFamily="var(--font-code)">
                {i + 1}
              </text>
              {[...run.cases].map((c, k) => (
                <circle
                  key={k}
                  cx={x(i)}
                  cy={LAMPS + k * ROW}
                  r="4.5"
                  fill={c === "1" && on ? "var(--base)" : "var(--panel)"}
                  stroke={c === "1" && on ? "var(--base)" : "var(--line)"}
                  style={{ transition: `fill 200ms ${k * 15}ms` }}
                />
              ))}
            </g>
          );
        })}

        <g fontSize="12" fill="var(--ink-2)">
          <text x={LEFT - 8} y={TOP + PANEL + 22} textAnchor="end">run</text>
          <text x={(x(0) + x(7)) / 2} y={TOP + PANEL + 40} textAnchor="middle">25 October, CI</text>
          <text x={(x(8) + x(10)) / 2} y={TOP + PANEL + 40} textAnchor="middle">26 October</text>
          <line x1={(x(7) + x(8)) / 2} x2={(x(7) + x(8)) / 2} y1={TOP + PANEL + 28} y2={TOP + PANEL + 44} stroke="var(--line)" />
          {Array.from({ length: 10 }, (_, k) => (
            <text key={k} x={LEFT - 8} y={LAMPS + k * ROW + 4} textAnchor="end" fontSize="11">
              case {k + 1}
            </text>
          ))}
          <text x={W - RIGHT + 8} y={LAMPS + 4}>lit: passed</text>
          <text x={W - RIGHT + 8} y={LAMPS + 4 + ROW}>cases in order of</text>
          <text x={W - RIGHT + 8} y={LAMPS + 4 + ROW * 2}>how often they pass</text>
        </g>
      </svg>
    </div>
  );
}
