/**
 * Turns a JSON Schema object into rows a reader can scan: one per field, nested fields under dotted paths
 * (`budgets.latency_s`, `checks[].id`), `$ref`s to small definitions inlined and to object definitions linked.
 */

export type Schema = { [key: string]: unknown };
/** Text, or a link to the section of a referenced definition. */
export type Part = string | { label: string; href: string };
export type Row = {
  path: string;
  /** The path's last segment; `path` minus `name` is the parent. */
  name: string;
  depth: number;
  required: boolean;
  type: Part[];
  description?: string;
  /** Constraints in words; `code` spans are in backticks. */
  rules: string[];
};
export type Condition = { when: string; rows: Row[] };
export type SchemaView = { title?: string; description?: string; rows: Row[]; conditions: Condition[] };

const obj = (v: unknown): v is Schema => !!v && typeof v === "object" && !Array.isArray(v);
const code = (v: unknown) => `\`${typeof v === "string" ? v : JSON.stringify(v)}\``;
const defName = (ref: string) => ref.slice(ref.lastIndexOf("/") + 1);

class Reader {
  constructor(
    private root: Schema,
    private links: Record<string, string>,
  ) {}

  /** The schema at a JSON pointer such as `#/$defs/step`. */
  at(pointer: string): Schema {
    const node = pointer
      .replace(/^#\/?/, "")
      .split("/")
      .filter(Boolean)
      .reduce<unknown>((n, key) => (obj(n) ? n[key.replace(/~1/g, "/").replace(/~0/g, "~")] : undefined), this.root);
    if (!obj(node)) throw new Error(`no schema at ${pointer}`);
    return node;
  }

  /** A `$ref` that is not linked is replaced by its target; the referring description wins. */
  private resolve(s: Schema): { schema: Schema; link?: Part } {
    if (typeof s.$ref !== "string") return { schema: s };
    const target = this.at(s.$ref);
    if (this.links[s.$ref]) return { schema: target, link: { label: defName(s.$ref), href: this.links[s.$ref] } };
    const merged = { ...target, ...s };
    delete merged.$ref;
    return { schema: merged };
  }

  type(raw: unknown): Part[] {
    if (!obj(raw)) return ["any"];
    const { schema: s, link } = this.resolve(raw);
    if (link) return [link];
    if ("const" in s) return [Number.isInteger(s.const) ? "integer" : s.const === null ? "null" : typeof s.const];
    if (Array.isArray(s.enum)) return [[...new Set(s.enum.map((v) => (v === null ? "null" : typeof v)))].join(" or ")];
    const variants = (s.anyOf ?? s.oneOf) as unknown;
    if (Array.isArray(variants)) return variants.flatMap((v, i) => (i ? [" or ", ...this.type(v)] : this.type(v)));
    const types = Array.isArray(s.type) ? (s.type as string[]) : typeof s.type === "string" ? [s.type] : [];
    if (!types.length) return obj(s.properties) ? ["object"] : ["any"];
    return types.flatMap((t, i) => {
      const part: Part[] =
        t === "array" && obj(s.items)
          ? ["array of ", ...this.type(s.items)]
          : t === "object" && !obj(s.properties) && obj(s.additionalProperties)
            ? ["map of name to ", ...this.type(s.additionalProperties)]
            : [t];
      return i ? [" or ", ...part] : part;
    });
  }

  rules(raw: Schema): string[] {
    const { schema: s, link } = this.resolve(raw);
    if (link) return [];
    const out: string[] = [];
    if ("const" in s) out.push(`always ${code(s.const)}`);
    if (Array.isArray(s.enum)) out.push(`one of ${s.enum.map(code).join(", ")}`);
    const bounds = [
      ["≥", s.minimum],
      [">", s.exclusiveMinimum],
      ["≤", s.maximum],
      ["<", s.exclusiveMaximum],
    ].filter(([, v]) => typeof v === "number");
    if (bounds.length) out.push(bounds.map(([op, v]) => `${op} ${v}`).join(" and "));
    if (s.minLength === 1) out.push("not empty");
    else if (typeof s.minLength === "number") out.push(`at least ${s.minLength} characters`);
    if (typeof s.minItems === "number") out.push(`at least ${s.minItems} item${s.minItems === 1 ? "" : "s"}`);
    if (typeof s.minProperties === "number") out.push(`at least ${s.minProperties} entr${s.minProperties === 1 ? "y" : "ies"}`);
    if (typeof s.pattern === "string") out.push(`matches ${code(s.pattern)}`);
    if (obj(s.propertyNames) && typeof s.propertyNames.pattern === "string") out.push(`names match ${code(s.propertyNames.pattern)}`);
    if (obj(s.items)) out.push(...this.rules(s.items).map((r) => `each: ${r}`));
    if (obj(s.additionalProperties) && !obj(s.properties) && !this.resolve(s.additionalProperties).link)
      out.push(...this.rules(s.additionalProperties).map((r) => `each: ${r}`));
    return out;
  }

  /** The fields of an object schema, children after their parent. */
  rows(raw: Schema, prefix = "", depth = 0): Row[] {
    const { schema: s, link } = this.resolve(raw);
    if (link || !obj(s.properties)) return [];
    const required = new Set(Array.isArray(s.required) ? (s.required as string[]) : []);
    return Object.entries(s.properties).flatMap(([name, child]) => {
      const field = obj(child) ? child : {};
      const { schema: resolved, link: linked } = this.resolve(field);
      const path = prefix + name;
      const row: Row = {
        path,
        name,
        depth,
        required: required.has(name),
        type: this.type(field),
        description: typeof resolved.description === "string" ? resolved.description : undefined,
        rules: this.rules(field),
      };
      if (linked) return [row];
      const nested = obj(resolved.properties)
        ? this.rows(resolved, `${path}.`, depth + 1)
        : obj(resolved.items)
          ? this.rows(resolved.items, `${path}[].`, depth + 1)
          : obj(resolved.additionalProperties)
            ? this.rows(resolved.additionalProperties, `${path}.<name>.`, depth + 1)
            : [];
      return [row, ...nested];
    });
  }

  /** `allOf: [{if, then}]`: fields that a value of another field requires or narrows. */
  conditions(raw: Schema): Condition[] {
    const { schema: s } = this.resolve(raw);
    if (!Array.isArray(s.allOf)) return [];
    const base = obj(s.properties) ? s.properties : {};
    return s.allOf.filter((c): c is Schema => obj(c) && obj(c.if) && obj(c.then)).map((c) => {
      const test = (c.if as Schema).properties;
      const when = obj(test)
        ? Object.entries(test)
            .filter(([, v]) => obj(v) && "const" in v)
            .map(([k, v]) => `${code(k)} is ${code((v as Schema).const)}`)
            .join(" and ")
        : "";
      const then = c.then as Schema;
      const required = Array.isArray(then.required) ? (then.required as string[]) : [];
      const props = obj(then.properties) ? then.properties : {};
      const names = [...new Set([...required, ...Object.keys(props)])];
      const rows = names.map((name): Row => {
        const field = obj(props[name]) ? (props[name] as Schema) : obj(base[name]) ? (base[name] as Schema) : {};
        const { schema: resolved } = this.resolve(field);
        return {
          path: name,
          name,
          depth: 0,
          required: required.includes(name),
          type: this.type(field),
          description: typeof resolved.description === "string" ? resolved.description : undefined,
          rules: this.rules(field),
        };
      });
      return { when, rows };
    });
  }
}

/**
 * The view of the object schema at `pointer` (default: the root) of `root`. `links` maps `$ref`s to the anchors of
 * the sections that document them; other `$ref`s are inlined.
 */
export function schemaView(root: Schema, pointer = "#", links: Record<string, string> = {}): SchemaView {
  const reader = new Reader(root, links);
  const s = reader.at(pointer);
  return {
    title: typeof s.title === "string" ? s.title : undefined,
    description: typeof s.description === "string" ? s.description : undefined,
    rows: reader.rows(s),
    conditions: reader.conditions(s),
  };
}
