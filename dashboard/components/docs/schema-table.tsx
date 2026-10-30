import { Fragment } from "react";
import { schemaView, type Part, type Row, type Schema } from "@/lib/schema";
import { Table } from "./prose";

/** Text with `code` spans in backticks, as schema descriptions write them. */
function Inline({ text }: { text: string }) {
  return text.split(/`([^`]+)`/).map((piece, i) => (i % 2 ? <code key={i}>{piece}</code> : <Fragment key={i}>{piece}</Fragment>));
}

function Type({ parts }: { parts: Part[] }) {
  return parts.map((p, i) =>
    typeof p === "string" ? (
      <Fragment key={i}>{p}</Fragment>
    ) : (
      <a key={i} href={p.href}>
        {p.label}
      </a>
    ),
  );
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Head() {
  return (
    <thead>
      <tr>
        <th scope="col" className="w-[38%]">
          Field
        </th>
        <th scope="col">Description</th>
      </tr>
    </thead>
  );
}

function Body({ rows }: { rows: Row[] }) {
  return (
    <tbody>
      {rows.map((r) => {
        const parent = r.path.slice(0, r.path.length - r.name.length);
        return (
          <tr key={r.path}>
            <td style={{ paddingLeft: `${r.depth * 1.25}rem` }}>
              <code className="border-0 bg-transparent p-0 font-mono text-sm font-bold [overflow-wrap:anywhere]">
                {parent && (
                  <span className="font-normal text-ink-3">
                    {parent.split(".").map((seg, i, all) => (
                      <Fragment key={i}>
                        {seg}
                        {i < all.length - 1 && (
                          <>
                            .<wbr />
                          </>
                        )}
                      </Fragment>
                    ))}
                  </span>
                )}
                {r.name}
              </code>
              <span className="mt-0.5 block text-sm text-ink-2">
                <Type parts={r.type} />
                {r.required && (
                  <>
                    , <b className="text-ink">required</b>
                  </>
                )}
              </span>
            </td>
            <td>
              {r.description && <Inline text={r.description} />}
              {r.rules.length > 0 && (
                <span className={`block text-ink-2 ${r.description ? "mt-1" : ""}`}>
                  <Inline text={capital(r.rules.join("; "))} />
                </span>
              )}
            </td>
          </tr>
        );
      })}
    </tbody>
  );
}

/**
 * The fields of the object schema at `at` (a JSON pointer into `schema`, default its root): name, type, whether it
 * is required, the description and constraints. `links` maps `$ref`s to the anchors of sections that document them;
 * other `$ref`s are shown in place. Fields that depend on another field's value (`if`/`then`) follow the table.
 */
export function SchemaTable({
  schema,
  at = "#",
  links,
  label,
  describe = true,
  source,
}: {
  schema: object;
  at?: string;
  links?: Record<string, string>;
  /** Names the table for screen readers, e.g. "Fields of gate.yaml". */
  label: string;
  /** Show the schema's own description above the table. */
  describe?: boolean;
  /** The schema file, named under the table. */
  source?: string;
}) {
  const view = schemaView(schema as Schema, at, links);
  return (
    <>
      {describe && view.description && (
        <p>
          <Inline text={view.description} />
        </p>
      )}
      {view.rows.length > 0 && (
        <Table label={label}>
          <Head />
          <Body rows={view.rows} />
        </Table>
      )}
      {source && <p className="mt-1.5! text-sm text-ink-2">from {source}</p>}
      {view.conditions.map((c) => (
        <Fragment key={c.when}>
          <p>
            When <Inline text={c.when} />:
          </p>
          <Table label={`${label} when ${c.when.replaceAll("`", "")}`}>
            <Head />
            <Body rows={c.rows} />
          </Table>
        </Fragment>
      ))}
    </>
  );
}
