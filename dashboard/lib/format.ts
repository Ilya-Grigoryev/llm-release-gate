export const score = (x: number | null | undefined) => (x == null ? "—" : x.toFixed(2));

export const points = (x: number | null | undefined) => (x == null ? "—" : `${x > 0 ? "+" : x < 0 ? "−" : "±"}${Math.abs(x).toFixed(1)}`);

export const usd = (x: number | null | undefined) => (x == null ? "—" : x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(3)}`);

export const short = (hash: string | null | undefined) => (hash ? hash.slice(0, 8) : "—");

const when = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Vienna" });

export const date = (iso: string) => when.format(new Date(iso));

export const seconds = (x: number | null | undefined) => (x == null ? "—" : x < 1 ? `${Math.round(x * 1000)} ms` : `${x.toFixed(1)} s`);
