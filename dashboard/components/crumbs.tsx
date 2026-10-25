import Link from "next/link";

export function Crumbs({ items }: { items: { href?: string; label: string }[] }) {
  return (
    <nav className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-ink-3">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span aria-hidden>/</span>}
          {item.href ? (
            <Link href={item.href} className="hover:text-ink">
              {item.label}
            </Link>
          ) : (
            <span className="text-ink-2">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

export function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {note && <div className="mt-0.5 text-xs text-ink-2">{note}</div>}
    </div>
  );
}
