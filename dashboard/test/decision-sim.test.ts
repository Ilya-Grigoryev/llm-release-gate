import { describe, expect, it } from "vitest";
import { simulate } from "../lib/decision-sim";

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
const halves = (k: number, copies: number) =>
  mean(Array.from({ length: 300 }, (_, s) => simulate({ k, breaking: false, copies, seed: s + 1 }).half!));

describe("the planned rule, simulated", () => {
  it("narrows the interval as the docs say: about 26, 12 and 5 points on 10 cases, half that on 40", () => {
    expect(halves(2, 1)).toBeGreaterThan(20);
    expect(halves(2, 1)).toBeLessThan(28);
    expect(halves(10, 1)).toBeCloseTo(11.5, 0);
    expect(halves(50, 1)).toBeCloseTo(5.2, 0);
    expect(halves(10, 4)).toBeCloseTo(halves(10, 1) / 2, 0);
  });

  it("blocks the breaking change on 40 cases from a few runs, and lets the naive rule decide one run", () => {
    expect(simulate({ k: 5, breaking: true, copies: 4, seed: 3 }).outcome).toBe("block");
    const one = simulate({ k: 1, breaking: false, copies: 1, seed: 3 });
    expect(one.half).toBeNull();
    expect(["pass", "block"]).toContain(one.outcome);
    expect(one.runs).toBe(20);
  });

  it("is the same for the same seed", () => {
    expect(simulate({ k: 10, breaking: false, copies: 1, seed: 7 })).toEqual(simulate({ k: 10, breaking: false, copies: 1, seed: 7 }));
  });
});
