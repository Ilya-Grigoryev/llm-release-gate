import { CommentCard, FigureHead } from "./kit";

/*
 * The example comment from the page, one line per block so that each line can carry its own marker. The text is the
 * gate's; GitHub shows the lines of one paragraph as separate lines anyway.
 */
const COMMENT = `
\`booking\` · **Release gate: ❌ quality fail**

Mean score 0.800 → 0.725 (-7.50 points, blocks below -5.00); naive rule: block if the mean drops by more than 5 points.

20 cases, first run of each version · config 3f9a1c0e → 8b42d7aa · set 51c0e9d2

False blocks: α 0.025 to the rule on checks; the naive rule on the mean has no α.

Checks: with 1 + 1 runs no break can be significant; a check broken in every run can block from 4 runs of each version (test over whole runs, α 0.025). 2 of 40 passed less often.

Cost of this decision $0.142: base $0.071, candidate $0.071 (successful calls, list prices).

Budget of the candidate not shown over its limits · cost $0.0036 per run (limit $0.005) · latency p95 7.10 s (interval 5.90–? s; limit 10 s), 1 of 20 runs needed retries.

| Case | Base | Candidate |
|---|---|---|
| cancel-after-deadline | 1.00 | 0.00 |
| cancel-on-arrival | 1.00 | 0.50 |

⚙️ This request changes the gate's rules for \`booking\` (gate.yaml or its prices). They apply after merge; until then the gate keeps the target branch's.

[Job log](https://github.com/OWNER/REPO/actions/runs/RUN_ID)
`;

/** Block index → the number of the list item above the figure that explains it. Item 4 is not in this comment. */
const MARKS = { 0: "1", 1: "2", 2: "3", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9" };

/** The comment, piece by piece. */
export default function ReadAVerdict1({}: { alt: string }) {
  return (
    <>
      <FigureHead tag="Example" />
      <CommentCard markdown={COMMENT} marks={MARKS} />
      <p className="mt-3 flex items-start gap-2 text-sm text-ink-2">
        <span
          aria-hidden
          className="mt-px grid size-5 shrink-0 place-items-center rounded-full border-[1.5px] border-dashed border-ink-3 font-mono text-[0.7rem] font-bold text-ink-2"
        >
          4
        </span>
        <span>
          <span className="sr-only">Marker 4: </span>
          Not in this example: the warning about a model without a date, which would sit between 3 and 5.
        </span>
      </p>
    </>
  );
}
