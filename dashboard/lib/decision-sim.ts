/**
 * A simulation of the planned rule for the docs (How it decides): both versions run K times per case; the difference
 * of means gets a 95 % interval from the spread of runs within each case (normal approximation), compared with −δ.
 * Pure: the seed decides every draw.
 */

/** The measured pass rate of each case of the author's support agent over 11 runs. */
export const PASS_RATES = [1, 1, 0.91, 0.64, 0.55, 0.45, 0.45, 0.36, 0.36, 0.36];

export type Outcome = "pass" | "block" | "not sure yet";
export type Draw = { diff: number; half: number | null; outcome: Outcome; runs: number };

/** mulberry32: a small seeded generator, so a draw can be shown again. */
function random(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** `k` runs of one case with pass rate `p`: their mean and their sample variance (0 with one run). */
function runs(p: number, k: number, next: () => number): { mean: number; variance: number } {
  let passed = 0;
  for (let i = 0; i < k; i++) if (next() < p) passed++;
  const mean = passed / k;
  return { mean, variance: k > 1 ? (passed * (1 - mean) ** 2 + (k - passed) * mean ** 2) / (k - 1) : 0 };
}

/**
 * One decision. `breaking` turns the two always-passing cases into always-failing ones (−20 points on 10 cases);
 * `copies` repeats the ten cases (4 → 40 cases); `delta` in points. With k = 1 there is no interval and the naive rule
 * decides.
 */
export function simulate({ k, breaking, copies, seed, delta = 5 }: { k: number; breaking: boolean; copies: number; seed: number; delta?: number }): Draw {
  const next = random(seed);
  const base = Array.from({ length: copies }, () => PASS_RATES).flat();
  const cand = base.map((p, i) => (breaking && i % PASS_RATES.length < 2 ? 0 : p));
  let diff = 0, variance = 0;
  for (let i = 0; i < base.length; i++) {
    const b = runs(base[i], k, next), c = runs(cand[i], k, next);
    diff += c.mean - b.mean;
    variance += (b.variance + c.variance) / k;
  }
  const n = base.length;
  const points = (100 * diff) / n;
  const runsTotal = 2 * k * n;
  if (k === 1) return { diff: points, half: null, outcome: points < -delta ? "block" : "pass", runs: runsTotal };
  const half = (100 * 1.96 * Math.sqrt(variance)) / n;
  const outcome: Outcome = points - half > -delta ? "pass" : points + half < -delta ? "block" : "not sure yet";
  return { diff: points, half, outcome, runs: runsTotal };
}
