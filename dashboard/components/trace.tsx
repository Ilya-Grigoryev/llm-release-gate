import type { Step } from "@/lib/artifact";
import { seconds } from "@/lib/format";
import { Fold, Json } from "./json";

const ACTOR: Record<string, string> = { agent: "agent", user: "user (simulated)", system: "system", env: "environment" };

function calls(step: Step): { name: string; args: unknown }[] {
  const raw = typeof step.tool_calls === "string" ? safeParse(step.tool_calls) : step.tool_calls;
  return Array.isArray(raw) ? raw : [];
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

const inline = (value: unknown) => {
  const text = JSON.stringify(value);
  return text && text.length > 160 ? `${text.slice(0, 160)}…` : text;
};

const text = (content: unknown) =>
  typeof content === "string" ? content : Array.isArray(content) ? content.map((c) => (typeof c === "string" ? c : c?.text ?? "")).join("\n") : null;

function Head({ kind, label, step, extra }: { kind: string; label: string; step: Step; extra?: string }) {
  const failed = step.status === "error";
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
      <span className="font-mono text-ink-3">{step.seq}</span>
      <span className={`rounded px-1.5 py-0.5 font-medium ${failed ? "bg-tint-bad text-bad" : "bg-canvas text-ink-2"}`}>{kind}</span>
      <span className="font-medium text-ink">{label}</span>
      {extra && <span className="text-ink-3">{extra}</span>}
      {step.latency_ms != null && <span className="text-ink-3">{seconds(step.latency_ms / 1000)}</span>}
      {failed && <span className="text-bad">failed</span>}
      {step.status === "unknown" && <span className="text-ink-3">status unknown</span>}
    </div>
  );
}

function One({ step }: { step: Step }) {
  if (step.kind === "llm") {
    const requested = calls(step);
    return (
      <>
        <Head kind="model" label={step.model ?? "model"} step={step} extra={step.tokens_in != null ? `${step.tokens_in} → ${step.tokens_out} tokens` : undefined} />
        {step.text && <p className="mt-1.5 text-sm whitespace-pre-wrap">{step.text}</p>}
        {requested.map((c, i) => (
          <p key={i} className="mt-1 font-mono text-xs break-all text-ink-2">
            calls {c.name}({inline(c.args)})
          </p>
        ))}
        {step.error != null && <Json value={step.error} />}
      </>
    );
  }
  if (step.kind === "tool") {
    return (
      <>
        <Head kind="tool" label={step.name ?? "tool"} step={step} />
        <p className="mt-1 font-mono text-xs break-all text-ink-2">{inline(step.args)}</p>
        {step.error != null ? <Json value={step.error} /> : step.result !== undefined && <Fold title="result" value={step.result} open={JSON.stringify(step.result).length < 240} />}
      </>
    );
  }
  if (step.kind === "message") {
    const body = text(step.content) ?? text(step.text);
    return (
      <>
        <Head kind="message" label={ACTOR[step.actor] ?? step.actor} step={step} />
        {body ? <p className="mt-1.5 text-sm whitespace-pre-wrap">{body}</p> : <Json value={step.content} />}
      </>
    );
  }
  return (
    <>
      <Head kind={step.kind} label={ACTOR[step.actor] ?? step.actor} step={step} />
      <Fold title="details" value={step} />
    </>
  );
}

/** The steps of one run in order; steps of an attempt the runner abandoned are dimmed. */
export function Steps({ steps, last }: { steps: Step[]; last?: number }) {
  return (
    <ol className="space-y-3 border-l border-line pl-3">
      {steps.map((step) => (
        <li key={`${step.run_attempt ?? 0}-${step.seq}`} className={last != null && (step.run_attempt ?? 0) < last ? "opacity-50" : undefined}>
          <One step={step} />
        </li>
      ))}
    </ol>
  );
}
