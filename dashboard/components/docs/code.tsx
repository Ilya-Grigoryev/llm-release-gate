import { CopyButton } from "./copy-button";

/**
 * A block of code or terminal input with a copy button. `filename` names the file it belongs in; `label` describes it
 * when there is no file (e.g. "Terminal").
 */
export function Code({ children, filename, label }: { children: string; filename?: string; label?: string }) {
  const text = children.replace(/^\n+|\s+$/g, "");
  const title = filename ?? label;
  return (
    <div data-code className="overflow-hidden rounded-md border border-line bg-panel">
      <div className="flex min-h-10 items-center justify-between gap-3 border-b border-line py-1.5 pr-2 pl-4">
        {title ? <span className={`truncate text-sm text-ink-2 ${filename ? "font-mono" : ""}`}>{title}</span> : <span />}
        <CopyButton text={text} />
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-sm leading-relaxed" tabIndex={0} aria-label={title ? `Code: ${title}` : "Code"}>
        <code>{text}</code>
      </pre>
    </div>
  );
}
