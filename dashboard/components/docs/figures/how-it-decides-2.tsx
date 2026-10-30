import { FigureHead } from "./kit";

const W = 540, LEFT = 52, TOP = 30, PANEL = 200;
const y = (v: number) => TOP + ((0.75 - v) / 0.4) * PANEL;
const BASE = 150, CAND = 250;

/** A blocked typo fix against the noise: the drop the naive rule blocked lies inside what the unchanged agent covers. */
export default function HowItDecides2() {
  return (
    <div>
      <FigureHead tag="The author's measurement on a support agent" />
      <svg viewBox={`0 0 ${W} ${y(0.4) + 14}`} className="w-full" role="presentation">
        <g fontSize="13" fill="var(--ink-2)" fontFamily="var(--font-code)">
          {[0.4, 0.5, 0.6, 0.7].map((v) => (
            <g key={v}>
              <line x1={LEFT} x2={W - 12} y1={y(v)} y2={y(v)} stroke="var(--line)" />
              <text x={LEFT - 8} y={y(v) + 4} textAnchor="end">
                {v.toFixed(2)}
              </text>
            </g>
          ))}
        </g>
        <rect x={LEFT} y={y(0.7)} width={W - LEFT - 12} height={y(0.4) - y(0.7)} fill="var(--ink-3)" opacity="0.12" />
        <text x={LEFT + 10} y={y(0.4) - 10} fontSize="13" fill="var(--ink-2)">
          the same agent, unchanged, 11 runs
        </text>

        <line x1={LEFT} x2={W - 12} y1={y(0.65)} y2={y(0.65)} stroke="var(--stop)" strokeWidth="1.5" strokeDasharray="6 5" />
        <text x={W - 12} y={y(0.65) - 8} textAnchor="end" fontSize="13" fill="var(--stop-ink)">
          the naive rule blocks below this line (base − 5 points)
        </text>

        <defs>
          <marker id="hid2-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="var(--ink)" />
          </marker>
        </defs>
        <circle cx={BASE} cy={y(0.7)} r="9" fill="var(--base)" />
        <text x={BASE} y={y(0.7) - 16} textAnchor="middle" fontSize="13" fill="var(--ink)" fontWeight="700">
          base 0.70
        </text>
        <path d={`M${BASE + 10} ${y(0.7) + 6} L${CAND - 13} ${y(0.6) - 7}`} stroke="var(--ink)" strokeWidth="1.5" markerEnd="url(#hid2-head)" />
        <text x={(BASE + CAND) / 2 - 10} y={(y(0.7) + y(0.6)) / 2 + 18} textAnchor="end" fontSize="13" fill="var(--ink)">
          −10 points
        </text>
        <circle cx={CAND} cy={y(0.6)} r="9" fill="var(--cand)" />
        <text x={CAND + 16} y={y(0.6) + 5} fontSize="13" fill="var(--ink)" fontWeight="700">
          typo fix 0.60
        </text>
        <circle cx={CAND + 122} cy={y(0.6)} r="6" fill="var(--stop)" />
        <text x={CAND + 134} y={y(0.6) + 5} fontSize="13" fill="var(--stop-ink)">
          blocked
        </text>
      </svg>
    </div>
  );
}
