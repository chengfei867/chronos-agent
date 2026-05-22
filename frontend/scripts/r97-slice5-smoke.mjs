#!/usr/bin/env node
// R97 slice 5 smoke check — exercise the `parseStepParam` helper from
// `src/App.tsx` against the AC matrix from CONTEXT.md §6:
//
//   - `?step=5`  → 5
//   - `?step=0`  → 0
//   - `?step=999` → 999 (clamping to totalSteps-1 happens in Replay.tsx,
//                          NOT in parseStepParam — this helper is pure
//                          parsing, not policy)
//   - `?step=-1` → undefined (negative ignored)
//   - `?step=foo` → undefined (non-integer ignored)
//   - `?step=5.5` → undefined (float ignored — strict integer regex)
//   - `?step=` → undefined (empty value treated as missing)
//   - `?other=1` → undefined (no step key)
//   - `""`       → undefined (no query at all)
//   - `?step=1&step=2` → 1 (URLSearchParams: first value wins)
//
// Plus a few "real" hash strings the way they'd appear in window.location.hash
// for end-to-end confidence.
//
// Run via:  cd frontend && node scripts/r97-slice5-smoke.mjs
//
// Lightweight invariant test; does NOT replace future RTL tests.

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { writeFileSync, unlinkSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repo = resolve(__dirname, "..");

const harness = `
import { parseStepParam } from "${repo}/src/App.tsx";

const cases = [
  { label: "?step=5",                  query: "?step=5",          expect: 5 },
  { label: "step=5 (no leading ?)",    query: "step=5",           expect: 5 },
  { label: "?step=0",                  query: "?step=0",          expect: 0 },
  { label: "?step=999 (no clamping)",  query: "?step=999",        expect: 999 },
  { label: "?step=-1 (negative)",      query: "?step=-1",         expect: undefined },
  { label: "?step=foo (non-int)",      query: "?step=foo",        expect: undefined },
  { label: "?step=5.5 (float)",        query: "?step=5.5",        expect: undefined },
  { label: "?step=5e1 (scientific)",   query: "?step=5e1",        expect: undefined },
  { label: "?step= (empty value)",     query: "?step=",           expect: undefined },
  { label: "?other=1 (wrong key)",     query: "?other=1",         expect: undefined },
  { label: "empty query",              query: "",                 expect: undefined },
  { label: "?step=1&step=2 (first wins)", query: "?step=1&step=2", expect: 1 },
  { label: "?other=x&step=7 (mixed)",  query: "?other=x&step=7",  expect: 7 },
  { label: "?step=  3  (whitespace)",  query: "?step=  3  ",      expect: undefined }, // strict regex rejects whitespace
];

let failed = 0;
for (const c of cases) {
  const got = parseStepParam(c.query);
  const ok = got === c.expect;
  console.log(\`\${ok ? "[OK]" : "[FAIL]"} \${c.label} -> got=\${JSON.stringify(got)} expected=\${JSON.stringify(c.expect)}\`);
  if (!ok) failed += 1;
}

// Type/identity invariants
const a = parseStepParam("?step=42");
if (typeof a !== "number" || !Number.isInteger(a) || a !== 42) {
  console.log("[FAIL] parseStepParam returns plain integer 42; got", a, typeof a);
  failed += 1;
} else {
  console.log("[OK] parseStepParam returns plain integer (no string coercion needed)");
}

const b = parseStepParam("?step=abc");
if (b !== undefined) {
  console.log("[FAIL] non-integer should be undefined, got", b);
  failed += 1;
} else {
  console.log("[OK] non-integer returns undefined (sentinel for 'no deep-link')");
}

if (failed > 0) {
  console.log(\`\\n*** \${failed} assertions FAILED ***\`);
  process.exit(1);
}
console.log("\\nR97 slice 5 smoke: ALL GREEN (parseStepParam invariants)");
`;

const tmp = resolve(repo, ".r97-slice5-harness.mts");
writeFileSync(tmp, harness);
const res = spawnSync("npx", ["tsx", tmp], {
  cwd: repo,
  stdio: "inherit",
  encoding: "utf8",
});
try { unlinkSync(tmp); } catch {}
process.exit(res.status ?? 1);
