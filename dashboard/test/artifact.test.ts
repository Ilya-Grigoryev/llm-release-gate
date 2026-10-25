import { strToU8, zipSync } from "fflate";
import { describe, expect, it } from "vitest";
import { compareCases, gateName, latest, parseArtifact, summarize, type Rec } from "../lib/artifact";

const rec = (fields: Partial<Rec> & Pick<Rec, "case">): Rec => ({ rep: 0, config_hash: "c1", score: 1, hits: {}, ...fields });
const lines = (rs: Rec[]) => rs.map((r) => JSON.stringify(r)).join("\n") + "\n";

const verdict = {
  outcome: "quality fail",
  exit_code: 10,
  base_mean: 1,
  candidate_mean: 0.5,
  diff_pp: -50,
  base_config: "c1",
  candidate_config: "c2",
  cost_usd: { base: 0.01, candidate: 0.02 },
};

describe("gateName", () => {
  it("reads the gate's name out of the artifact's", () => {
    expect(gateName("release-gate-1")).toBe("");
    expect(gateName("release-gate-support-3")).toBe("support");
    expect(gateName("release-gate-v2-1")).toBe("v2");
    expect(gateName("coverage-1")).toBeNull();
    expect(gateName("release-gate")).toBeNull();
  });
});

describe("parseArtifact", () => {
  const base = [
    rec({ case: "book", trace: { steps: [{ seq: 0, kind: "llm", actor: "agent", text: "Booked." }] } }),
    rec({ case: "receipt", hits: { company: true, total: true }, trace: null }),
  ];
  const candidate = [
    rec({ case: "book", config_hash: "c2", score: 0, hits: { state: false } }),
    rec({ case: "receipt", config_hash: "c2", hits: { company: true, total: true } }),
  ];
  const zip = zipSync({
    "verdict.json": strToU8(JSON.stringify(verdict)),
    "comment.md": strToU8("**Release gate: ❌ quality fail**"),
    "base.jsonl": strToU8(lines(base) + '{"case": "cut off by a cra'),
    "candidate.jsonl": strToU8(lines(candidate)),
    "candidate.native.jsonl": strToU8("not read"),
  });

  it("reads the verdict, the comment and the records, skipping a broken line", () => {
    const p = parseArtifact(zip);
    expect(p.verdict?.outcome).toBe("quality fail");
    expect(p.comment).toContain("quality fail");
    expect(p.base.map((r) => r.case)).toEqual(["book", "receipt"]);
    expect(p.base[1].trace).toBeNull();
    expect(p.candidate).toHaveLength(2);
  });

  it("summarizes a verdict", () => {
    expect(summarize(parseArtifact(zip))).toEqual({
      outcome: "quality fail",
      exit_code: 10,
      base_mean: 1,
      candidate_mean: 0.5,
      diff_pp: -50,
      cost: 0.03,
      same_version: false,
    });
  });

  it("calls a run without a verdict an infra error", () => {
    const p = parseArtifact(zipSync({ "comment.md": strToU8("**Release gate: ⚠️ infra error**"), "base.jsonl": strToU8(lines(base)) }));
    expect(p.verdict).toBeNull();
    expect(summarize(p)).toMatchObject({ outcome: "infra error", exit_code: 20, base_mean: null, same_version: null });
  });
});

describe("latest", () => {
  it("keeps the last record without an error, else the last one", () => {
    const rs = [
      rec({ case: "a", score: 0.1 }),
      rec({ case: "a", score: null, error: "timeout" }),
      rec({ case: "b", error: "first" }),
      rec({ case: "b", error: "second" }),
      rec({ case: "c", error: "first" }),
      rec({ case: "c", score: 0.7 }),
    ];
    const by = Object.fromEntries(latest(rs).map((r) => [r.case, r]));
    expect(by.a.score).toBe(0.1);
    expect(by.b.error).toBe("second");
    expect(by.c.score).toBe(0.7);
  });
});

describe("compareCases", () => {
  it("puts changed cases first, the most worsened at the top, and names the checks that flipped", () => {
    const base = [
      rec({ case: "same", hits: { x: true } }),
      rec({ case: "worse", hits: { x: true, y: true } }),
      rec({ case: "slightly", score: 1, hits: { x: true } }),
      rec({ case: "better", score: 0, hits: { x: false } }),
    ];
    const candidate = [
      rec({ case: "same", hits: { x: true } }),
      rec({ case: "worse", score: 0, hits: { x: true, y: false } }),
      rec({ case: "slightly", score: 0.5, hits: { x: true } }),
      rec({ case: "better", score: 1, hits: { x: true } }),
    ];
    const rows = compareCases(base, candidate);
    expect(rows.map((r) => r.case)).toEqual(["worse", "slightly", "better", "same"]);
    expect(rows[0].flipped).toEqual(["y"]);
    expect(rows[1].flipped).toEqual([]);
    expect(rows[3].changed).toBe(false);
  });

  it("compares repetitions by their mean and share of passing checks", () => {
    const base = [rec({ case: "a", rep: 0, score: 1, hits: { x: true } }), rec({ case: "a", rep: 1, score: 0, hits: { x: false } })];
    const candidate = [rec({ case: "a", rep: 0, score: 0, hits: { x: false } }), rec({ case: "a", rep: 1, score: 1, hits: { x: true } })];
    const [row] = compareCases(base, candidate);
    expect(row.baseMean).toBe(0.5);
    expect(row.flipped).toEqual([]);
    expect(row.changed).toBe(false);
  });

  it("counts a case that errs on one side only as changed", () => {
    const [row] = compareCases([rec({ case: "a" })], [rec({ case: "a", error: "boom" })]);
    expect(row.changed).toBe(true);
  });
});
