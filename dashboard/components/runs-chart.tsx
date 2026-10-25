"use client";

import { useEffect, useRef, useState } from "react";
import { points as pts } from "@/lib/format";
import { look, Outcome } from "./outcome";

export type Point = {
  href: string;
  label: string;
  title: string | null;
  when: string;
  outcome: string;
  base: number;
  candidate: number;
  same: boolean | null;
};

const H = 228;
const PAD = { top: 12, right: 12, bottom: 44, left: 40 };
const PLOT = H - PAD.top - PAD.bottom;

/** The score range to draw: the data with some air, on round steps, at least 0.2 wide, inside 0–1. */
function domain(points: Point[]): { lo: number; hi: number; step: number } {
  const values = points.flatMap((p) => [p.base, p.candidate]);
  let lo = Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10);
  let hi = Math.min(1, Math.ceil((Math.max(...values) + 0.05) * 10) / 10);
  if (hi - lo < 0.2) {
    hi = Math.min(1, lo + 0.2);
    lo = Math.max(0, hi - 0.2);
  }
  const range = hi - lo;
  return { lo, hi, step: range <= 0.3 ? 0.05 : range <= 0.6 ? 0.1 : 0.25 };
}

/**
 * One column per run, oldest on the left: the target branch's mean (ring) and the pull request's (dot), an arrow from
 * one to the other, and the verdict under the column. The line above the chart reads out the column under the pointer.
 */
export function RunsChart({ points }: { points: Point[] }) {
  const [active, setActive] = useState(points.length - 1);
  // Drawn at the container's pixel width, so text keeps its size on any screen.
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(720);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setW(Math.max(260, Math.round(entry.contentRect.width))));
    if (box.current) observer.observe(box.current);
    return () => observer.disconnect();
  }, []);
  const { lo, hi, step } = domain(points);
  const ticks = Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step);
  const col = (W - PAD.left - PAD.right) / points.length;
  const x = (i: number) => PAD.left + (i + 0.5) * col;
  const y = (v: number) => PAD.top + ((hi - v) / (hi - lo)) * PLOT;
  const every = Math.max(1, Math.ceil(points.length / Math.floor((W - PAD.left - PAD.right) / 64)));
  // Marks closer than they are wide sit side by side; equal ones nest.
  const dodge = (p: Point) => {
    const gap = Math.abs(y(p.candidate) - y(p.base));
    return gap >= 1 && gap < 13 ? 7 : 0;
  };
  const shown = points[active];
  const diff = shown.candidate - shown.base;

  return (
    <figure>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div aria-live="polite" className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 font-medium">{shown.label}</span>
            <span className="truncate text-sm text-ink-2">{shown.title}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <Outcome value={shown.outcome} />
            <span className="tabular-nums text-ink-2">
              {shown.base.toFixed(2)} → <span className="font-medium text-ink">{shown.candidate.toFixed(2)}</span>{" "}
              <span className={diff < 0 ? "text-bad" : ""}>{pts(diff * 100)} points</span>
            </span>
            <span className="text-ink-3">{shown.when}</span>
            {shown.same && <span className="text-ink-3">same version on both sides, so the gap is noise</span>}
          </div>
        </div>
        <figcaption className="flex shrink-0 gap-4 pt-1 text-xs text-ink-2">
          <span className="inline-flex items-center gap-1.5">
            <svg viewBox="0 0 12 12" className="size-3" aria-hidden>
              <circle cx={6} cy={6} r={4.5} fill="var(--panel)" stroke="var(--base)" strokeWidth={2} />
            </svg>
            target branch
          </span>
          <span className="inline-flex items-center gap-1.5">
            <svg viewBox="0 0 12 12" className="size-3" aria-hidden>
              <circle cx={6} cy={6} r={4} fill="var(--cand)" />
            </svg>
            pull request
          </span>
        </figcaption>
      </div>

      <div ref={box} className="mt-4">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block overflow-visible" role="img" aria-label="Mean score of the target branch and of the pull request in each run">
        <defs>
          <marker id="head" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
            <path d="M0 0.5 L7.5 4 L0 7.5 z" fill="var(--ink-2)" />
          </marker>
        </defs>
        <rect x={x(active) - col / 2} y={PAD.top - 6} width={col} height={PLOT + 12} rx={6} fill="var(--canvas)" />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={PAD.left - 10} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--ink-3)" className="tabular-nums">
              {t.toFixed(step < 0.1 ? 2 : 1)}
            </text>
          </g>
        ))}
        <polyline
          points={points.map((p, i) => `${x(i) - dodge(p)},${y(p.base)}`).join(" ")}
          fill="none"
          stroke="var(--base)"
          strokeWidth={1.5}
          strokeDasharray="3 4"
          opacity={0.6}
        />
        {points.map((p, i) => {
          const from = y(p.base);
          const to = y(p.candidate);
          const gap = Math.abs(to - from);
          const dir = Math.sign(to - from);
          const s = look(p.outcome);
          const d = dodge(p);
          return (
            <g key={p.href}>
              {gap > 24 && (
                <line x1={x(i)} x2={x(i)} y1={from + dir * 8} y2={to - dir * 7} stroke="var(--ink-2)" strokeWidth={1.5} markerEnd="url(#head)" />
              )}
              <circle cx={x(i) - d} cy={from} r={6} fill="var(--panel)" stroke="var(--base)" strokeWidth={2} />
              <circle cx={x(i) + d} cy={to} r={gap < 1 ? 3 : 4.5} fill="var(--cand)" stroke="var(--panel)" strokeWidth={gap < 1 ? 0 : 1.5} />
              <g transform={`translate(${x(i)}, ${H - PAD.bottom + 18})`}>
                <circle r={6} fill={s.color} />
                <text dy="0.35em" textAnchor="middle" fontSize={8} fontWeight={700} fill={s.ink}>
                  {s.icon}
                </text>
                {(i % every === 0 || i === active) && (
                  <text y={17} textAnchor="middle" fontSize={11} fill={i === active ? "var(--ink)" : "var(--ink-2)"}>
                    {p.label.length > 14 ? `${p.label.slice(0, 13)}…` : p.label}
                  </text>
                )}
              </g>
            </g>
          );
        })}
        {points.map((p, i) => (
          <a key={p.href} href={p.href} aria-label={`${p.label}, ${p.outcome}: ${p.base.toFixed(2)} to ${p.candidate.toFixed(2)}`}>
            <rect
              x={x(i) - col / 2}
              y={0}
              width={col}
              height={H}
              fill="transparent"
              className="cursor-pointer outline-none focus-visible:stroke-[var(--ink-2)]"
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
            />
          </a>
        ))}
      </svg>
      </div>
    </figure>
  );
}
