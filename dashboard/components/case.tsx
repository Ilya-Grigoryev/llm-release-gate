import type { CaseFile, Input } from "@/lib/artifact";
import { Fold, Json } from "./json";

const scalar = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);

/** The prose fields of a structured input (a ticket, a task description): what a reader looks for first. */
function prose(value: unknown): [string, string][] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).filter((e): e is [string, string] => typeof e[1] === "string" && e[1].trim().includes(" "));
}

function One({ name, input }: { name: string; input: Input }) {
  const head = <h3 className="mb-1.5 text-xs text-ink-3">{name}</h3>;
  if (input.text === undefined)
    return (
      <div>
        {head}
        {input.large ? (
          <p className="text-sm text-ink-3">{input.path}: too large to show here</p>
        ) : input.url ? (
          <a href={input.url} target="_blank" rel="noreferrer" className="text-sm underline underline-offset-4 hover:text-ink">
            {input.path.slice(input.path.lastIndexOf("/") + 1)}
          </a>
        ) : (
          <p className="text-sm text-ink-3">{input.path}: not in the run&apos;s artifact</p>
        )}
      </div>
    );
  const fields = prose(input.parsed);
  return (
    <div>
      {head}
      {input.parsed === undefined ? (
        <pre className="max-h-72 overflow-auto rounded-md bg-canvas p-3 font-mono text-xs whitespace-pre-wrap text-ink-2">{input.text}</pre>
      ) : (
        <div className="space-y-2">
          {fields.map(([key, text]) => (
            <div key={key}>
              <div className="text-xs text-ink-3">{key}</div>
              <p className="text-sm whitespace-pre-wrap">{text.trim()}</p>
            </div>
          ))}
          <Fold title={fields.length ? `all of ${input.path}` : input.path} value={input.parsed} open={!fields.length && input.text.length < 600} />
        </div>
      )}
    </div>
  );
}

export function Expected({ value }: { value: unknown }) {
  if (value && typeof value === "object" && !Array.isArray(value) && Object.values(value).every(scalar))
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {Object.entries(value).map(([key, v]) => (
          <div key={key} className="contents">
            <dt className="text-ink-3">{key}</dt>
            <dd className="break-words">{v == null ? "—" : String(v)}</dd>
          </div>
        ))}
      </dl>
    );
  return <Json value={value ?? null} />;
}

/** What the golden set gives the case and what it expects back. */
export function CasePanel({ file }: { file: CaseFile }) {
  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-2">
      <section className="min-w-0 space-y-4 rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">Input</h2>
        {Object.entries(file.inputs).map(([name, input]) => (
          <One key={name} name={name} input={input} />
        ))}
      </section>
      <section className="min-w-0 space-y-3 rounded-lg border border-line bg-panel p-4">
        <h2 className="font-medium">Expected</h2>
        <Expected value={file.spec.expected} />
      </section>
    </div>
  );
}
