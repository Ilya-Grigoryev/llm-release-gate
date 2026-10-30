import type { ReactNode } from "react";

export type Lamp = "go" | "stop" | "wait" | "neutral";

export type VerdictKind =
  | "pass"
  | "quality fail"
  | "budget fail"
  | "inconclusive"
  | "infra error"
  | "unchanged"
  | "no base version"
  | "not checked";

/** The lamp each verdict lights: go lets the merge through, stop blocks it, wait is not sure yet, neutral decided nothing. */
export const LAMP: Record<VerdictKind, Lamp> = {
  pass: "go",
  "quality fail": "stop",
  "budget fail": "stop",
  inconclusive: "wait",
  "infra error": "neutral",
  unchanged: "neutral",
  "no base version": "neutral",
  "not checked": "neutral",
};

/** A signal lamp; neutral is a lamp that is not lit. */
export function LampDot({ lamp, className = "size-3" }: { lamp: Lamp; className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block shrink-0 rounded-full ${className}`}
      style={
        lamp === "neutral"
          ? { boxShadow: "inset 0 0 0 2px var(--neutral)" }
          : { background: `var(--${lamp})`, boxShadow: `0 0 0 3px color-mix(in srgb, var(--${lamp}) 22%, transparent)` }
      }
    />
  );
}

/** A verdict as the gate names it, with its lamp. `children` replaces the name, e.g. to quote a comment. */
export function Verdict({ kind, children }: { kind: VerdictKind; children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-panel py-0.5 pr-3 pl-2 align-middle text-base leading-6 font-bold whitespace-nowrap text-ink">
      <LampDot lamp={LAMP[kind]} className="size-2.5" />
      {children ?? kind}
    </span>
  );
}
