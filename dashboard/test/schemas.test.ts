import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = new URL("../../src/llm_release_gate/", import.meta.url);
const copy = new URL("../content/schemas/", import.meta.url);

// The site renders the reference from copies; a copy that lags its source shows wrong fields.
describe.skipIf(!existsSync(src))("schema copies", () => {
  it.each(["project", "protocol", "case"])("%s matches its source (npm run sync-schemas)", (name) => {
    const file = `${name}.schema.json`;
    expect(readFileSync(new URL(file, copy), "utf8")).toBe(readFileSync(new URL(file, src), "utf8"));
  });
});
