import { Children, isValidElement, type ReactNode } from "react";
import { slugify } from "@/lib/docs";

/** The text inside headings, links, code and the like: what an id is made from. */
export function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return Children.toArray(node).map(textOf).join("");
}

/** Long-form text: headings, paragraphs, lists, tables and inline code in the docs' type. */
export function Prose({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`prose ${className}`}>{children}</div>;
}

/** The paragraph under a page's title that says what the page is for. */
export function Lead({ children }: { children: ReactNode }) {
  return <p className="lead">{children}</p>;
}

/** A section heading. "On this page" lists every H2; the id comes from the text unless given. */
export function H2({ id, children }: { id?: string; children: ReactNode }) {
  return <h2 id={id ?? slugify(textOf(children))}>{children}</h2>;
}

export function H3({ id, children }: { id?: string; children: ReactNode }) {
  return <h3 id={id ?? slugify(textOf(children))}>{children}</h3>;
}

/** A table that scrolls inside itself on a narrow screen instead of widening the page. */
export function Table({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="table-scroll" role={label ? "region" : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      <table>{children}</table>
    </div>
  );
}
