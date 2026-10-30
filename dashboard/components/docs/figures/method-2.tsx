import { FigureHead, LampDot, type Lamp } from "./kit";

// Positions on the axis, in per cent of its width: −δ and 0, then each interval's ends and its estimate.
const DELTA = 35;
const ZERO = 65;
const RULES = ["Prove harm", "Prove harmlessness", "Three outcomes"];

type Answer = { lamp: Lamp; word: string; note?: string };
const PASS: Answer = { lamp: "go", word: "pass" };
const BLOCK: Answer = { lamp: "stop", word: "block" };

const ROWS: { label: string; from: number; to: number; at: number; answers: Answer[]; marked?: boolean }[] = [
  { label: "clearly within δ", from: 57, to: 75, at: 66, answers: [PASS, PASS, PASS] },
  { label: "clearly worse", from: 8, to: 26, at: 17, answers: [BLOCK, BLOCK, BLOCK] },
  { label: "few runs", from: 15, to: 85, at: 48, answers: [PASS, BLOCK, { lamp: "wait", word: "not sure yet", note: "run more" }], marked: true },
  { label: "worse, by less than δ", from: 42, to: 58, at: 50, answers: [PASS, PASS, { lamp: "go", word: "pass", note: "with a warning" }] },
];

const COLS = "sm:grid-cols-[minmax(0,1fr)_repeat(3,6.5rem)] sm:gap-x-3";

/** The line at 0 (solid) and at −δ (dashed), from the top of a cell to its bottom. */
function Margins() {
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 h-full w-full">
      <line x1={`${DELTA}%`} x2={`${DELTA}%`} y1="0" y2="100%" stroke="var(--ink-3)" strokeWidth="1.5" strokeDasharray="4 3" />
      <line x1={`${ZERO}%`} x2={`${ZERO}%`} y1="0" y2="100%" stroke="var(--ink-3)" strokeWidth="1.5" />
    </svg>
  );
}

function Interval({ from, to, at }: { from: number; to: number; at: number }) {
  const ends = [from, to].map((x) => <line key={x} x1={`${x}%`} x2={`${x}%`} y1="4" y2="16" stroke="var(--ink)" strokeWidth="2" />);
  return (
    <svg aria-hidden className="relative block h-5 w-full overflow-visible">
      <line x1={`${from}%`} x2={`${to}%`} y1="10" y2="10" stroke="var(--ink)" strokeWidth="2.5" />
      {ends}
      <circle cx={`${at}%`} cy="10" r="4.5" fill="var(--ink)" />
    </svg>
  );
}

/** Three ways to decide. */
export default function Method2() {
  return (
    <div>
      <FigureHead tag="Illustration" />

      <div aria-hidden className={`hidden pb-2 text-sm leading-snug font-bold sm:grid ${COLS}`}>
        <span />
        {RULES.map((r) => (
          <span key={r}>
            {r}
            {r === "Three outcomes" && <span className="block font-normal text-ink-2">planned</span>}
          </span>
        ))}
      </div>

      <ol>
        {ROWS.map((row, i) => (
          <li key={row.label} className={`grid ${COLS} ${row.marked ? "rounded-md bg-paper outline-1 outline-ink-3" : ""}`}>
            <div className="relative min-w-0 pt-2 pb-1.5 sm:py-3">
              <Margins />
              <p className={`relative ml-1 w-fit px-1 text-sm ${row.marked ? "bg-paper font-bold" : "bg-panel"}`}>
                <span className="font-mono text-ink-3">{i + 1}</span> {row.label}
              </p>
              <Interval {...row} />
            </div>
            <ul className="grid grid-cols-3 gap-2 px-2 pb-3 sm:contents">
              {row.answers.map((a, k) => (
                <li key={k} className="min-w-0 sm:py-3">
                  <span className="block min-h-8 text-xs text-ink-2 sm:sr-only">
                    {RULES[k]}
                    {k === 2 && " (planned)"}:
                  </span>
                  <span className="flex items-start gap-1.5 text-sm leading-snug">
                    <LampDot lamp={a.lamp} className="mt-1 size-2.5" />
                    <span>
                      {a.word}
                      {a.note && <span className="block text-xs text-ink-2">{a.note}</span>}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <div className={`grid ${COLS}`}>
        <div className="relative pb-1 text-sm text-ink-2">
          <svg aria-hidden className="block h-2.5 w-full overflow-visible">
            <line x1="0" x2="100%" y1="0" y2="0" stroke="var(--ink-3)" strokeWidth="1.5" />
            <line x1={`${DELTA}%`} x2={`${DELTA}%`} y1="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.5" />
            <line x1={`${ZERO}%`} x2={`${ZERO}%`} y1="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.5" />
          </svg>
          <div className="relative h-5 font-mono">
            <span className="absolute -translate-x-1/2" style={{ left: `${DELTA}%` }}>
              −δ
            </span>
            <span className="absolute -translate-x-1/2" style={{ left: `${ZERO}%` }}>
              0
            </span>
          </div>
          <p className="mt-1 flex justify-between gap-2 text-xs">
            <span>worse</span>
            <span>better</span>
          </p>
          <p className="text-center">difference in points (candidate − base)</p>
        </div>
      </div>

      <p className="mt-3 text-sm text-ink-2">
        Row 3: the two rules with two outcomes disagree, and each gives a definite answer it has no evidence for.
      </p>
    </div>
  );
}
