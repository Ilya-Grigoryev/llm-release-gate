import { describe, expect, it } from "vitest";
import caseSchema from "../content/schemas/case.schema.json";
import project from "../content/schemas/project.schema.json";
import protocol from "../content/schemas/protocol.schema.json";
import { schemaView, type Part, type Row, type Schema } from "../lib/schema";

const text = (parts: Part[]) => parts.map((p) => (typeof p === "string" ? p : `[${p.label}](${p.href})`)).join("");
const byPath = (rows: Row[]) => Object.fromEntries(rows.map((r) => [r.path, r]));

function sane(rows: Row[]) {
  for (const r of rows) {
    expect(text(r.type), r.path).not.toMatch(/undefined|^$/);
    for (const rule of r.rules) expect(rule, r.path).not.toMatch(/undefined|NaN/);
  }
}

describe("schemaView", () => {
  it("reads gate.yaml: links object definitions, inlines small ones", () => {
    const view = schemaView(project as Schema, "#", { "#/$defs/pipeline": "#pipeline", "#/$defs/budgets": "#budgets" });
    const rows = byPath(view.rows);
    expect(view.title).toBe("gate.yaml");
    expect(Object.keys(rows)).toEqual(["prepare", "ignore", "pipelines", "k", "delta", "prices", "budgets", "base_max_age_days"]);
    expect(rows.pipelines.required).toBe(true);
    expect(text(rows.pipelines.type)).toBe("map of name to [pipeline](#pipeline)");
    expect(rows.pipelines.rules).toEqual(["at least 1 entry", "names match `^[A-Za-z0-9_-][A-Za-z0-9._-]*$`"]);
    expect(text(rows.prepare.type)).toBe("array of string");
    expect(rows.prepare.rules).toEqual(["at least 1 item", "each: not empty"]);
    expect(text(rows.k.type)).toBe("integer");
    expect(rows.k.rules).toEqual(["≥ 1"]);
    expect(rows.k.description).toMatch(/Runs per case/);
    expect(text(rows.budgets.type)).toBe("[budgets](#budgets)");
    sane(view.rows);

    const pipeline = byPath(schemaView(project as Schema, "#/$defs/pipeline", { "#/$defs/budgets": "#budgets" }).rows);
    expect(pipeline.config.required && pipeline.golden.required).toBe(true);
    expect(Object.keys(pipeline)).toContain("inputs-url");
    const budgets = byPath(schemaView(project as Schema, "#/$defs/budgets").rows);
    expect(budgets.latency_quantile.rules).toEqual(["> 0 and < 1"]);
  });

  it("reads a case: maps, enums and nested arrays of objects", () => {
    const view = schemaView(caseSchema as Schema);
    const rows = byPath(view.rows);
    expect(Object.keys(rows)).toEqual([
      "id",
      "version",
      "slices",
      "source",
      "input",
      "expected",
      "scoring",
      "scoring.method",
      "scoring.aggregate",
      "scoring.checks",
      "scoring.checks[].id",
      "scoring.checks[].kind",
      "note",
    ]);
    expect(text(rows.input.type)).toBe("map of name to string");
    expect(rows["scoring.aggregate"].rules).toEqual(["one of `mean`, `all`"]);
    expect(text(rows["scoring.checks"].type)).toBe("array of object");
    expect(rows["scoring.checks[].id"].required).toBe(true);
    sane(view.rows);
  });

  it("reads the protocol: const, anyOf, type lists, untyped fields and conditions", () => {
    const links = { "#/$defs/step": "#step" };
    const request = byPath(schemaView(protocol as Schema, "#/$defs/request", links).rows);
    expect(request.protocol.rules).toEqual(["always `1`"]);
    expect(text(request.protocol.type)).toBe("integer");
    expect(text(request["config.prompt"].type)).toBe("string or map of name to string");
    expect(text(request["case.inputs"].type)).toBe("map of name to string");

    const answer = schemaView(protocol as Schema, "#/$defs/answer", links);
    const rows = byPath(answer.rows);
    expect(text(rows.output.type)).toBe("object or null");
    expect(text(rows.raw.type)).toBe("any");
    expect(text(rows.input_tokens.type)).toBe("integer");
    expect(rows.input_tokens.rules).toEqual(["≥ 0"]);
    expect(text(rows["trace.steps"].type)).toBe("array of [step](#step)");
    expect(text(rows["trace.final_state"].type)).toBe("any");
    sane(answer.rows);

    const step = schemaView(protocol as Schema, "#/$defs/step", links);
    expect(step.rows.map((r) => r.path)).toEqual(["kind", "actor", "ts"]);
    expect(step.conditions.map((c) => c.when)).toEqual([
      "`kind` is `llm`",
      "`kind` is `tool`",
      "`kind` is `llm` and `status` is `ok`",
      "`kind` is `llm` and `status` is `error`",
    ]);
    const ok = byPath(step.conditions[2].rows);
    expect(Object.keys(ok)).toEqual(["model", "tokens_in", "tokens_out", "cost_usd"]);
    expect(ok.cost_usd.rules).toEqual(["≥ 0"]);
    expect(text(ok.cost_usd.type)).toBe("number or null");
    for (const c of step.conditions) sane(c.rows);
  });
});
