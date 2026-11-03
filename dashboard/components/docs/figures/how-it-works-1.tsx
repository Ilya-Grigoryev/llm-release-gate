import type { ReactNode } from "react";
import { Arrow, CommentCard, FigureHead, Key, LampDot, Node } from "./kit";

type Arm = "base" | "cand";

const WORSE = { 2: "cancel-after-deadline", 8: "cancel-on-arrival" } as Record<number, string>;
// First run of each of the 20 cases: four cases fail on both sides; the candidate loses two more, one by half.
const BASE = [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1];
const CAND = BASE.map((s, i) => (i === 2 ? 0 : i === 8 ? 0.5 : s));

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
const minus = (x: number) => x.toFixed(2).replace("-", "−");

const ARM: Record<Arm, { name: string; tree: string; hash: string; scores: number[] }> = {
  base: { name: "main (base)", tree: "the target branch's tree, its lock file", hash: "3f9a1c0e", scores: BASE },
  cand: { name: "this request (candidate)", tree: "the request's tree, its lock file", hash: "8b42d7aa", scores: CAND },
};

const COMMENT = `
\`booking\` · **Release gate: quality fail**

Mean score 0.800 → 0.725 (-7.50 points, blocks below -5.00); naive rule: block if the mean drops by more than 5 points.
20 cases, first run of each version · config 3f9a1c0e → 8b42d7aa · set 51c0e9d2
Checks: with 1 + 1 runs no break can be significant; a single broken check can block from 4 runs of each version (one-sided Fisher, α 0.025). 2 of 40 passed less often.
Cost of this decision $0.142: base $0.071, candidate $0.071 (successful calls, list prices).

| Case | Base | Candidate |
|---|---|---|
| cancel-after-deadline | 1.00 | 0.00 |
| cancel-on-arrival | 1.00 | 0.50 |

[Job log](https://github.com/OWNER/REPO/actions/runs/RUN_ID)
`;

/** The number of the step in the list above that a stage belongs to. */
function Num({ n }: { n: number }) {
  return (
    <span aria-label={`Step ${n}:`} className="mr-1.5 inline-grid size-5 place-items-center rounded-full bg-ink align-[0.1em] font-mono text-[0.7rem] font-bold text-panel">
      {n}
    </span>
  );
}

/** Both versions side by side, each on its own rail in its colour; stacked on a phone. */
function Tracks({ children }: { children: (arm: Arm) => ReactNode }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:gap-6">
      {(["base", "cand"] as const).map((arm) => (
        <div key={arm} className="min-w-0 border-l-2 pl-3" style={{ borderColor: `var(--${arm})` }}>
          <p className="mb-2 text-sm text-ink-2">{ARM[arm].name}</p>
          {children(arm)}
        </div>
      ))}
    </div>
  );
}

/** A case lamp: filled from the bottom by the case's score, in its version's colour. */
function CaseLamp({ arm, score, worse }: { arm: Arm; score: number; worse: boolean }) {
  const color = `var(--${arm})`;
  return (
    <span
      className={`relative block size-3.5 overflow-hidden rounded-full ${worse ? "outline-2 outline-offset-2 outline-ink" : ""}`}
      style={{ boxShadow: `inset 0 0 0 1.5px ${color}` }}
    >
      <span className="absolute inset-x-0 bottom-0" style={{ height: `${score * 100}%`, background: color }} />
    </span>
  );
}

/** A lamp of the barrier: lit, off (a ring in its colour), or dimmed because this rule cannot give it. */
function BarrierLamp({ lamp, on, label, note }: { lamp: "go" | "stop" | "wait"; on: boolean; label: string; note?: string }) {
  return (
    <li className={`flex items-center gap-2 ${note ? "opacity-55" : ""}`}>
      {on ? (
        <LampDot lamp={lamp} className="size-4" />
      ) : (
        <span aria-hidden className="inline-block size-4 shrink-0 rounded-full" style={{ boxShadow: `inset 0 0 0 2px var(--${lamp})` }} />
      )}
      <span className={on ? "font-bold" : undefined}>
        {label}
        {on ? <span className="sr-only"> (lit)</span> : !note && <span className="sr-only"> (off)</span>}
      </span>
      {note && <span className="text-sm text-ink-2">{note}</span>}
    </li>
  );
}

/** One request through the gate. */
export default function HowItWorks1() {
  const [mb, mc] = [mean(BASE), mean(CAND)];
  return (
    <div>
      <FigureHead tag="Example">
        <Key
          items={[
            { color: "var(--base)", label: "main (base)" },
            { color: "var(--cand)", label: "the request (candidate)" },
          ]}
        />
      </FigureHead>

      <Node title={<><Num n={1} />The job starts</>}>not from a fork, a valid gate.yaml, allowed to comment</Node>
      <Arrow down />

      <Tracks>
        {(arm) => (
          <>
            <Node tone={arm} title={<><Num n={2} />checkout and dependencies</>}>{ARM[arm].tree}</Node>
            <Arrow down />
            <Node tone={arm} title={<><Num n={3} />version hash</>}>
              <span className="font-mono">{ARM[arm].hash}</span>
            </Node>
          </>
        )}
      </Tracks>
      <Arrow down />

      <div className="flex flex-col items-stretch sm:flex-row sm:items-center">
        <Node className="sm:flex-1" title={<><Num n={3} />same version hash?</>}>
          <span className="font-mono">{ARM.base.hash}</span> and <span className="font-mono">{ARM.cand.hash}</span> differ, so both
          versions run
          <span className="mt-1.5 flex items-center gap-2 border-t border-line pt-1.5 sm:hidden">
            <LampDot lamp="neutral" />
            if equal: unchanged, nothing runs
          </span>
        </Node>
        <div className="hidden sm:contents">
          <Arrow label="if equal" muted />
          <Node dashed tone="muted" className="w-56" title={<span className="flex items-center gap-2"><LampDot lamp="neutral" />unchanged</span>}>
            nothing runs, no model is called
          </Node>
        </div>
      </div>
      <Arrow down label="they differ" />

      <Tracks>
        {(arm) => (
          <>
            <div className="rounded-md border border-line bg-panel px-3 py-2">
              <p className="leading-snug font-bold">
                <Num n={4} />
                20 cases, first run
              </p>
              <ol aria-label={`Case scores, ${ARM[arm].name}`} className="mt-2.5 grid w-fit grid-cols-10 gap-2">
                {ARM[arm].scores.map((s, i) => (
                  <li key={i} title={`${WORSE[i] ?? `case ${i + 1}`}: ${s.toFixed(2)}`}>
                    <CaseLamp arm={arm} score={s} worse={arm === "cand" && i in WORSE} />
                    <span className="sr-only">{`${WORSE[i] ?? `case ${i + 1}`}: ${s.toFixed(2)}`}</span>
                  </li>
                ))}
              </ol>
              {arm === "cand" && (
                <ul className="mt-2.5 space-y-0.5 text-sm text-ink-2">
                  <li className="flex items-center gap-2">
                    <span aria-hidden className="inline-block size-2.5 rounded-full outline-2 outline-offset-1 outline-ink" />
                    worse than main:
                  </li>
                  <li className="font-mono [overflow-wrap:anywhere]">cancel-after-deadline 1.00 → 0.00</li>
                  <li className="font-mono [overflow-wrap:anywhere]">cancel-on-arrival 1.00 → 0.50</li>
                </ul>
              )}
            </div>
            <Arrow down />
            <Node tone={arm} title={<><Num n={5} />checks</>}>score each run from 0 to 1</Node>
          </>
        )}
      </Tracks>
      <Arrow down />

      <div className="rounded-md border-2 border-ink-3 bg-panel px-3 py-3 sm:px-4">
        <p className="leading-snug font-bold">
          <Num n={6} />
          The gate decides: naive rule
        </p>
        <div className="mt-3 grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          <dl className="space-y-1">
            {([["base", mb], ["cand", mc]] as const).map(([arm, m]) => (
              <div key={arm} className="flex items-center gap-2">
                <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: `var(--${arm})` }} />
                <dt className="text-ink-2">{arm === "base" ? "main" : "request"}, mean</dt>
                <dd className="font-mono">{m.toFixed(3)}</dd>
              </div>
            ))}
            <div className="flex flex-wrap items-baseline gap-x-2 pt-1">
              <dt className="text-ink-2">difference</dt>
              <dd className="font-mono font-bold">{minus((mc - mb) * 100)} points</dd>
              <dd className="text-ink-2">
                limit <span className="font-mono">−5.00</span>
              </dd>
            </div>
          </dl>
          <ul aria-label="Barrier lamps" className="space-y-1.5 border-t border-line pt-3 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-5">
            <BarrierLamp lamp="go" on={false} label="pass" />
            <BarrierLamp lamp="stop" on label="block" />
            <BarrierLamp lamp="wait" on={false} label="not sure yet" note="betting rule only" />
          </ul>
        </div>
      </div>
      <Arrow down label="the comment on the request" />

      <CommentCard markdown={COMMENT} compact />
    </div>
  );
}
