"use client";

import { useState } from "react";

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

const W = 720;
const H = 220;
const PAD = { top: 14, right: 64, bottom: 24, left: 36 };
const TICKS = [0, 0.25, 0.5, 0.75, 1];

/** Each run as a dumbbell: the target branch's mean (base) and the pull request's (candidate), oldest run on the left. */
export function RunsChart({ points }: { points: Point[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = W - PAD.left - PAD.right;
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const x = (i: number) => PAD.left + (points.length > 1 ? i * step : width / 2);
  const y = (v: number) => PAD.top + (1 - v) * (H - PAD.top - PAD.bottom);
  const last = points.length - 1;
  const hit = Math.max(step, 16);
  const near = last >= 0 && Math.abs(points[last].base - points[last].candidate) < 0.08;
  const shown = hover == null ? null : points[hover];

  return (
    <figure className="relative">
      <figcaption className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-base" /> target branch (base)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-cand" /> pull request (candidate)
        </span>
        <span className="text-ink-3">mean score per run, 0–1</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Mean score of the base and the candidate in each run">
        {TICKS.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--ink-3)">
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        <polyline
          points={points.map((p, i) => `${x(i)},${y(p.base)}`).join(" ")}
          fill="none"
          stroke="var(--base)"
          strokeWidth={2}
          strokeLinejoin="round"
          opacity={0.5}
        />
        {points.map((p, i) => (
          <g key={p.href} opacity={hover == null || hover === i ? 1 : 0.35}>
            <line x1={x(i)} x2={x(i)} y1={y(p.base)} y2={y(p.candidate)} stroke="var(--ink-3)" strokeWidth={1.5} />
            <circle cx={x(i)} cy={y(p.base)} r={4.5} fill="var(--base)" stroke="var(--panel)" strokeWidth={2} />
            <circle cx={x(i)} cy={y(p.candidate)} r={4.5} fill="var(--cand)" stroke="var(--panel)" strokeWidth={2} />
          </g>
        ))}
        {last >= 0 && (
          <g fontSize={11} fill="var(--ink-2)">
            <text x={x(last) + 10} y={y(points[last].base) + (near && points[last].base <= points[last].candidate ? 8 : 0)} dy="0.32em">
              base
            </text>
            <text x={x(last) + 10} y={y(points[last].candidate) - (near && points[last].base <= points[last].candidate ? 8 : 0)} dy="0.32em">
              candidate
            </text>
          </g>
        )}
        {points.map((p, i) => (
          <a key={p.href} href={p.href} aria-label={`${p.label}: base ${p.base.toFixed(2)}, candidate ${p.candidate.toFixed(2)}`}>
            <rect
              x={x(i) - hit / 2}
              y={0}
              width={hit}
              height={H}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            />
          </a>
        ))}
      </svg>
      {shown && (
        <div
          className="pointer-events-none absolute top-6 z-10 w-60 -translate-x-1/2 rounded-md border border-line bg-panel p-2.5 text-xs shadow-lg"
          style={{ left: `${(Math.min(Math.max(x(hover!), 120), W - 120) / W) * 100}%` }}
        >
          <div className="font-medium text-ink">{shown.label}</div>
          {shown.title && <div className="truncate text-ink-2">{shown.title}</div>}
          <div className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-ink-2">
            <span>base</span>
            <span className="tabular-nums">{shown.base.toFixed(2)}</span>
            <span>candidate</span>
            <span className="tabular-nums">{shown.candidate.toFixed(2)}</span>
            <span>verdict</span>
            <span>{shown.outcome}</span>
          </div>
          {shown.same && <div className="mt-1.5 text-ink-3">Same version on both sides: the gap is noise.</div>}
          <div className="mt-1 text-ink-3">{shown.when}</div>
        </div>
      )}
    </figure>
  );
}
