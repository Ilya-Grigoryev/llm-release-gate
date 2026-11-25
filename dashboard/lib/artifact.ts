import { strFromU8, unzipSync } from "fflate";
import { parse as parseYaml } from "yaml";

/** One step of a trace (D-019): a model call, a tool call, a message or a retrieval. */
export type Step = {
  seq: number;
  kind: "llm" | "tool" | "message" | "retrieval";
  actor: string;
  status?: string;
  latency_ms?: number;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_usd?: number | null;
  finish_reason?: string | null;
  text?: string | null;
  tool_calls?: { id?: string; name: string; args: unknown }[] | string | null;
  name?: string;
  args?: unknown;
  result?: unknown;
  error?: unknown;
  content?: unknown;
  run_attempt?: number;
  [field: string]: unknown;
};

export type Trace = {
  steps: Step[];
  final_state?: unknown;
  state_change?: unknown;
  stop?: string | null;
  last_attempt?: number;
};

/** One run of one case, as the gate's runner writes it. */
export type Rec = {
  case: string;
  rep: number;
  config_hash: string;
  timestamp?: string;
  model?: string | null;
  output?: unknown;
  raw?: unknown;
  hits?: Record<string, boolean | number | null> | null;
  score?: number | null;
  score_error?: unknown;
  error?: unknown;
  input_tokens?: number | null;
  output_tokens?: number | null;
  latency_s?: number | null;
  retries?: number;
  scorer_version?: string;
  trace?: Trace | null;
};

export type Verdict = {
  outcome: string;
  exit_code: number;
  base_mean: number;
  candidate_mean: number;
  diff_pp: number;
  limit_pp?: number;
  rule?: string;
  cases?: number;
  worse?: [string, number, number][];
  base_config?: string;
  candidate_config?: string;
  set_hash?: string;
  scorer_version?: string;
  cost_usd?: { base: number | null; candidate: number | null };
  models_without_date?: string[];
  runs_per_case?: { base: number; candidate: number };
  mean?: { lower: number; upper: number; delta: number; decided_at: number | null } | null;
  /** `pr` only: what the request changed in the test set (D-035); `outcome` is the verdict on the request's set. */
  set_change?: {
    files: string[];
    added: string[];
    removed: string[];
    edited: string[];
    manifest?: "changed" | "removed" | null;
    outcome: string;
  } | null;
};

/** A test-set change in words, as the comment names it: the cases added, removed and edited, a dropped manifest, else the files. */
export function setChange(c: NonNullable<Verdict["set_change"]>): string {
  const named = (xs: string[]) => xs.slice(0, 5).join(", ") + (xs.length > 5 ? ` and ${xs.length - 5} more` : "");
  const parts = (["added", "removed", "edited"] as const).filter((k) => c[k].length).map((k) => `${k}: ${named(c[k])}`);
  if (c.manifest === "removed") parts.push("manifest dropped");
  return parts.length ? parts.join("; ") : `files: ${named(c.files)}`;
}

export type Parsed = { verdict: Verdict | null; comment: string | null; base: Rec[]; candidate: Rec[] };

const ARTIFACT = /^release-gate(?:-(.+))?-(\d+)$/;

/** The gate's name and the run attempt of an artifact the gate action uploaded (`release-gate[-NAME]-ATTEMPT`), or null for any other artifact. */
export function gateArtifact(artifact: string): { gate: string; attempt: number } | null {
  const m = ARTIFACT.exec(artifact);
  return m ? { gate: m[1] ?? "", attempt: Number(m[2]) } : null;
}

const FILES = new Set(["verdict.json", "comment.md", "base.jsonl", "candidate.jsonl"]);
const basename = (path: string) => path.slice(path.lastIndexOf("/") + 1);

export function parseArtifact(zip: Uint8Array): Parsed {
  const files = unzipSync(zip, { filter: (f) => FILES.has(basename(f.name)) });
  const text = (name: string) => {
    const hit = Object.entries(files).find(([path]) => basename(path) === name);
    return hit ? strFromU8(hit[1]) : null;
  };
  const verdict = text("verdict.json");
  return {
    verdict: verdict ? JSON.parse(verdict) : null,
    comment: text("comment.md"),
    base: latest(jsonl(text("base.jsonl"))),
    candidate: latest(jsonl(text("candidate.jsonl"))),
  };
}

/** The records of a JSON-lines file; a line cut off by a crash is skipped, as the runner does. */
function jsonl(text: string | null): Rec[] {
  const records: Rec[] = [];
  for (const line of text?.split("\n") ?? []) {
    try {
      if (line.trim()) records.push(JSON.parse(line));
    } catch {}
  }
  return records;
}

/** The record the gate compares for each (case, repetition): the last one without an error, else the last one. */
export function latest(records: Rec[]): Rec[] {
  const by = new Map<string, Rec>();
  for (const r of records) {
    const key = `${r.case}\u0000${r.rep}`;
    const prev = by.get(key);
    if (!prev || !r.error || prev.error) by.set(key, r);
  }
  return [...by.values()];
}

export type Summary = {
  outcome: string;
  exit_code: number;
  base_mean: number | null;
  candidate_mean: number | null;
  diff_pp: number | null;
  cost: number | null;
  same_version: boolean | null;
};

export function summarize({ verdict, base, candidate }: Parsed): Summary {
  const config = (rs: Rec[]) => rs[0]?.config_hash;
  if (!verdict) {
    const same = config(base) && config(candidate) ? config(base) === config(candidate) : null;
    return { outcome: "infra error", exit_code: 20, base_mean: null, candidate_mean: null, diff_pp: null, cost: null, same_version: same };
  }
  const costs = [verdict.cost_usd?.base, verdict.cost_usd?.candidate].filter((c): c is number => typeof c === "number");
  return {
    outcome: verdict.outcome,
    exit_code: verdict.exit_code,
    base_mean: verdict.base_mean,
    candidate_mean: verdict.candidate_mean,
    diff_pp: verdict.diff_pp,
    cost: costs.length ? costs.reduce((a, b) => a + b, 0) : null,
    same_version: verdict.base_config && verdict.candidate_config ? verdict.base_config === verdict.candidate_config : null,
  };
}

export type CaseRow = {
  case: string;
  base: Rec[];
  candidate: Rec[];
  baseMean: number | null;
  candidateMean: number | null;
  /** Checks whose share of passing repetitions differs between the two versions. */
  flipped: string[];
  changed: boolean;
};

const mean = (xs: (number | null | undefined)[]) => {
  const ok = xs.filter((x): x is number => typeof x === "number");
  return ok.length ? ok.reduce((a, b) => a + b, 0) / ok.length : null;
};

export const share = (rs: Rec[], check: string) => mean(rs.map((r) => (r.hits?.[check] == null ? null : Number(r.hits[check]))));

/** The cases side by side, the ones that changed first and the most worsened among them first. */
export function compareCases(base: Rec[], candidate: Rec[]): CaseRow[] {
  const names = [...new Set([...base, ...candidate].map((r) => r.case))];
  const rows = names.map((name) => {
    const b = base.filter((r) => r.case === name).sort((x, y) => x.rep - y.rep);
    const c = candidate.filter((r) => r.case === name).sort((x, y) => x.rep - y.rep);
    const checks = [...new Set([...b, ...c].flatMap((r) => Object.keys(r.hits ?? {})))];
    const flipped = checks.filter((check) => share(b, check) !== share(c, check));
    const baseMean = mean(b.map((r) => r.score));
    const candidateMean = mean(c.map((r) => r.score));
    const errors = (rs: Rec[]) => rs.some((r) => r.error);
    const changed = baseMean !== candidateMean || flipped.length > 0 || errors(b) !== errors(c);
    return { case: name, base: b, candidate: c, baseMean, candidateMean, flipped, changed };
  });
  const delta = (r: CaseRow) => (r.candidateMean ?? 0) - (r.baseMean ?? 0);
  return rows.sort((x, y) => Number(y.changed) - Number(x.changed) || delta(x) - delta(y) || x.case.localeCompare(y.case));
}

/** One input of a case: a file of the golden set, with its text when it is small text, else where to find it. */
export type Input = { path: string; text?: string; parsed?: unknown; url?: string; large?: boolean };

/** A case as the golden set defines it (id, input, expected, scoring), with its inputs. */
export type CaseFile = { spec: Record<string, unknown>; inputs: Record<string, Input> };

const TEXT = /\.(ya?ml|json|txt|md|csv)$/i;
/**
 * The cases of the golden set the gate action uploads next to the records, by case id, with their text inputs up to
 * 64 KB. For the other files (images) the action leaves out, `inputs-url.txt` says where they are.
 */
export function parseCases(zip: Uint8Array): Record<string, CaseFile> {
  const rel = (path: string) => (path.startsWith("cases/") ? path.slice("cases/".length) : path);
  const present = new Set<string>();
  const files = unzipSync(zip, {
    filter: (f) => (present.add(rel(f.name)), TEXT.test(f.name) && f.originalSize <= 64 * 1024),
  });
  const text = new Map(Object.entries(files).map(([path, bytes]) => [rel(path), strFromU8(bytes)]));
  const template = text.get("inputs-url.txt")?.trim();
  const url = (ref: string) =>
    template?.startsWith("https://")
      ? template
          .replaceAll("{path}", ref.split("/").map(encodeURIComponent).join("/"))
          .replaceAll("{name}", encodeURIComponent(ref.slice(ref.lastIndexOf("/") + 1)))
      : undefined;
  const cases: Record<string, CaseFile> = {};
  for (const [path, body] of text) {
    if (path.includes("/") || !/\.ya?ml$/i.test(path)) continue; // case files sit at the set's root
    const spec = structured(path, body) as Record<string, unknown> | undefined;
    if (!spec || typeof spec !== "object" || typeof spec.id !== "string") continue;
    const inputs: Record<string, Input> = {};
    const input = spec.input && typeof spec.input === "object" ? Object.entries(spec.input) : [];
    for (const [key, value] of input) {
      if (typeof value !== "string") continue;
      const ref = value.replace(/^\.\//, "");
      const body = text.get(ref);
      inputs[key] =
        body !== undefined
          ? { path: ref, text: body, parsed: structured(ref, body) }
          : present.has(ref) && TEXT.test(ref)
            ? { path: ref, large: true }
            : { path: ref, url: url(ref) };
    }
    cases[spec.id] = { spec, inputs };
  }
  return cases;
}

function structured(path: string, body: string): unknown {
  try {
    // YAML 1.1, as the gate reads it (PyYAML), so values like `yes` and `012` mean the same on both sides.
    return /\.json$/i.test(path) ? JSON.parse(body) : /\.ya?ml$/i.test(path) ? parseYaml(body, { version: "1.1" }) : undefined;
  } catch {
    return undefined;
  }
}
