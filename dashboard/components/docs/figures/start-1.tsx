import type { ReactNode } from "react";
import { FigureHead } from "./kit";

/** The anchors of the page's steps (the ids its headings get). */
const STEP: Record<number, string> = {
  1: "1-get-access-while-the-gate-is-private",
  2: "2-add-the-dependency",
  3: "3-write-gate-yaml",
  4: "4-describe-the-version-and-connect-your-app",
  5: "5-write-a-first-case",
  6: "6-add-the-gate-to-your-workflow",
};

type Row = { name: string; depth?: number; step?: number; edited?: boolean; note?: ReactNode; kept?: boolean };

const TREE: Row[] = [
  { name: ".github/workflows/" },
  { name: "release-gate.yml", depth: 1, step: 6 },
  { name: "configs/" },
  { name: "invoice.yaml", depth: 1, step: 4 },
  { name: "golden/invoices/" },
  { name: "inputs/", depth: 1 },
  { name: "inv-001.txt", depth: 2, step: 5 },
  { name: "inv-001.yaml", depth: 1, step: 5 },
  { name: "prompts/" },
  { name: "extract.md", depth: 1, step: 4 },
  { name: "src/invoice_reader/" },
  { name: "__init__.py", depth: 1, kept: true, note: "already there" },
  { name: "gate_adapter.py", depth: 1, step: 4 },
  { name: ".gitignore", step: 5, edited: true, note: <>adds <code className="font-mono">.env</code> and <code className="font-mono">runs/</code></> },
  { name: "gate.yaml", step: 3 },
  { name: "pyproject.toml", step: 2, edited: true },
  { name: "uv.lock", step: 2, edited: true },
];

const SECRETS: Row[] = [
  { name: "LLM_RELEASE_GATE_KEY", step: 1 },
  { name: "OPENAI_API_KEY", step: 6 },
];

function StepNo({ step }: { step: number }) {
  return (
    <span className="grid size-5 shrink-0 place-items-center rounded-full border border-ink-3 bg-paper font-mono text-xs font-bold text-ink">
      <span className="sr-only">step </span>
      {step}
    </span>
  );
}

function Line({ row }: { row: Row }) {
  const name = <span className={`font-mono text-sm break-all ${row.kept ? "text-ink-3" : row.step ? "text-ink" : "text-ink-2"}`}>{row.name}</span>;
  const body = (
    <>
      <span className="min-w-0">
        {name}
        {row.note && <span className={`block text-sm leading-snug ${row.kept ? "text-ink-3" : "text-ink-2"}`}>{row.note}</span>}
      </span>
      {row.step && (
        <span className="flex shrink-0 items-center gap-2 text-sm text-ink-2">
          {row.edited && "edited"}
          <StepNo step={row.step} />
        </span>
      )}
    </>
  );
  const box = "flex items-center justify-between gap-3 rounded py-0.5 pr-1";
  const indent = { paddingLeft: `${0.25 + (row.depth ?? 0) * 1.25}rem` };
  return (
    <li className="mt-0">
      {row.step ? (
        <a href={`#${STEP[row.step]}`} className={`${box} text-ink no-underline hover:bg-paper`} style={indent}>
          {body}
        </a>
      ) : (
        <div className={box} style={indent}>
          {body}
        </div>
      )}
    </li>
  );
}

function Box({ title, rows, className = "" }: { title: string; rows: Row[]; className?: string }) {
  return (
    <div className={`min-w-0 rounded-md border border-line p-2 ${className}`}>
      <p className="px-1 pb-1 text-sm text-ink-2">{title}</p>
      <ul role="list" className="list-none pl-0">
        {rows.map((row) => (
          <Line key={row.name} row={row} />
        ))}
      </ul>
    </div>
  );
}

/** What you add to your repository. */
export default function Start1({}: { alt: string }) {
  return (
    <>
      <FigureHead tag="Example" />
      <div className="grid items-start gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,15rem)]">
        <Box title="invoice-reader, the repository" rows={TREE} />
        <Box title="Repository secrets, not files" rows={SECRETS} />
      </div>
    </>
  );
}
