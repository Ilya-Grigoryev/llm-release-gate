// Copies the gate's JSON schemas next to the site, which renders the reference from them: node scripts/sync-schemas.mjs
import { copyFileSync, mkdirSync } from "node:fs";

const NAMES = ["project", "protocol", "case"];
const src = new URL("../../src/llm_release_gate/", import.meta.url);
const dest = new URL("../content/schemas/", import.meta.url);

mkdirSync(dest, { recursive: true });
for (const name of NAMES) copyFileSync(new URL(`${name}.schema.json`, src), new URL(`${name}.schema.json`, dest));
console.log(`copied ${NAMES.length} schemas`);
