import type { MDXComponents } from "mdx/types";
import Link from "next/link";
import { isValidElement, type ComponentProps, type ReactNode } from "react";
import { Callout } from "@/components/docs/callout";
import { Code } from "@/components/docs/code";
import { Fig } from "@/components/docs/figures";
import { LanguageTabs, Tab } from "@/components/docs/language-tabs";
import { H2, H3, Lead, Prose, Table, textOf } from "@/components/docs/prose";
import { SchemaTable } from "@/components/docs/schema-table";
import { Verdict } from "@/components/docs/verdict";

const LANGUAGE: Record<string, string> = {
  sh: "Terminal",
  bash: "Terminal",
  console: "Terminal",
  shell: "Terminal",
  yaml: "YAML",
  yml: "YAML",
  json: "JSON",
  python: "Python",
  py: "Python",
  js: "JavaScript",
  javascript: "JavaScript",
  ts: "TypeScript",
  go: "Go",
  markdown: "Markdown",
  md: "Markdown",
  text: "Text",
};

/** A fenced block: MDX gives `<pre><code className="language-x">`; the docs show it with a label and a copy button. */
function Pre({ children }: { children?: ReactNode }) {
  const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children : null;
  const language = code?.props.className?.replace("language-", "") ?? "";
  return <Code label={LANGUAGE[language] ?? (language || undefined)}>{textOf(code?.props.children ?? children)}</Code>;
}

/** Links inside the docs go through the router; links out open in place, as any link. */
function A({ href = "", children, ...rest }: ComponentProps<"a">) {
  if (href.startsWith("/") || href.startsWith("#")) return <Link href={href}>{children}</Link>;
  return (
    <a href={href} {...rest}>
      {children}
    </a>
  );
}

const components: MDXComponents = {
  wrapper: ({ children }) => <Prose>{children}</Prose>,
  h2: ({ children }) => <H2>{children}</H2>,
  h3: ({ children }) => <H3>{children}</H3>,
  table: ({ children }) => <Table>{children}</Table>,
  pre: Pre,
  a: A,
  Callout,
  Fig,
  LanguageTabs,
  Lead,
  SchemaTable,
  Tab,
  Verdict,
};

export function useMDXComponents(): MDXComponents {
  return components;
}
