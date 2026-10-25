export function Json({ value }: { value: unknown }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-canvas p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-ink-2">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Fold({ title, value, open = false }: { title: string; value: unknown; open?: boolean }) {
  return (
    <details open={open} className="group">
      <summary className="cursor-pointer text-xs text-ink-3 select-none hover:text-ink-2">{title}</summary>
      <div className="mt-1.5">
        <Json value={value} />
      </div>
    </details>
  );
}
