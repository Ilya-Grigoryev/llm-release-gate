const LOOK: Record<string, { color: string; ink: string; icon: string }> = {
  pass: { color: "var(--good)", ink: "#fff", icon: "✓" },
  "quality fail": { color: "var(--bad)", ink: "#fff", icon: "✕" },
  "budget fail": { color: "var(--bad)", ink: "#fff", icon: "$" },
  inconclusive: { color: "var(--warn)", ink: "#1b1a18", icon: "?" },
  "infra error": { color: "var(--none)", ink: "#fff", icon: "!" },
  unchanged: { color: "var(--none)", ink: "#fff", icon: "=" },
};

export const look = (outcome: string) => LOOK[outcome] ?? LOOK["infra error"];

export const blocks = (outcome: string) => outcome === "quality fail" || outcome === "budget fail";

export function Outcome({ value }: { value: string }) {
  const look = LOOK[value] ?? LOOK["infra error"];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span
        aria-hidden
        className="grid size-4 shrink-0 place-items-center rounded-full text-[10px] leading-none font-bold"
        style={{ background: look.color, color: look.ink }}
      >
        {look.icon}
      </span>
      {value}
    </span>
  );
}

export function Hit({ value }: { value: boolean | number | null | undefined }) {
  if (value == null) return <span className="text-ink-3">—</span>;
  return Number(value) >= 1 ? <span className="text-good">✓</span> : Number(value) <= 0 ? <span className="text-bad">✕</span> : <span>{Number(value).toFixed(2)}</span>;
}
