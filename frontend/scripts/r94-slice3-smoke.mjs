#!/usr/bin/env node
// R94 slice 3 smoke check — invoke `formatAnthropicAgents` against a
// synthesized multi-block state_after and assert the discriminated payload
// shape is correct for each block kind. Lightweight invariant test;
// does NOT replace future RTL tests.
//
// Run via:  cd frontend && node scripts/r94-slice3-smoke.mjs
//
// This is a deliberate one-shot script — no test runner, no deps beyond
// the in-repo TS we tsx-compile inline. Falls back to importing the
// already-compiled module via `ts-node`/`tsx` when available, or simply
// reads the source and pattern-matches the surface (last-resort).

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repo = resolve(__dirname, "..");

// Use `tsx` (already a dev-dep transitive of vite) to run the TS file.
const harness = `
import { formatAnthropicAgents } from "${repo}/src/format/adapters/anthropic_agents.ts";

function asNode(state_after) {
  return {
    id: "n1",
    run_id: "r1",
    parent_id: null,
    kind: "llm",
    name: "anthropic_step",
    inputs: null,
    state_after,
    started_at: "2026-05-22T00:00:00Z",
    finished_at: "2026-05-22T00:00:01Z",
    tool_use_ids: [],
  };
}

const cases = [
  {
    label: "TextBlock",
    state: {
      envelope: "AssistantMessage",
      model: "claude-sonnet-4.5",
      blocks: [{ block: { type: "text", text: "Hello world!" } }],
    },
    expectKind: "text",
  },
  {
    label: "ToolUseBlock",
    state: {
      envelope: "AssistantMessage",
      model: "claude-sonnet-4.5",
      tool_use_ids: ["toolu_abc"],
      blocks: [
        {
          block: {
            type: "tool_use",
            id: "toolu_abc",
            name: "search_web",
            input: { query: "ai news", limit: 5 },
          },
        },
      ],
    },
    expectKind: "tool_use",
  },
  {
    label: "ToolResultBlock (string)",
    state: {
      envelope: "UserMessage",
      blocks: [
        {
          block: {
            type: "tool_result",
            tool_use_id: "toolu_abc",
            content: "Result: 42",
            is_error: false,
          },
        },
      ],
    },
    expectKind: "tool_result",
  },
  {
    label: "ToolResultBlock (list of text chunks)",
    state: {
      envelope: "UserMessage",
      blocks: [
        {
          block: {
            type: "tool_result",
            tool_use_id: "toolu_abc",
            content: [{ type: "text", text: "first" }, { type: "text", text: "second" }],
            is_error: true,
          },
        },
      ],
    },
    expectKind: "tool_result",
  },
  {
    label: "Unknown block (fall-through to json)",
    state: {
      envelope: "AssistantMessage",
      blocks: [{ block: { type: "thinking", text: "..." } }],
    },
    expectKind: "json",
  },
];

let failed = 0;
for (const c of cases) {
  const formatted = formatAnthropicAgents(asNode(c.state));
  const blockSection = formatted.sections.find(s => s.id.startsWith("block-"));
  const payload = blockSection?.payload;
  const ok = payload && typeof payload === "object" && payload.kind === c.expectKind;
  console.log(\`\${ok ? "[OK]" : "[FAIL]"} \${c.label} -> kind=\${typeof payload === "object" ? payload?.kind : "string"} (expected \${c.expectKind})\`);
  if (!ok) failed += 1;
}

// Specific shape assertions
const tu = formatAnthropicAgents(asNode(cases[1].state)).sections.find(s => s.id === "block-0").payload;
if (tu.kind !== "tool_use" || tu.name !== "search_web" || tu.toolUseId !== "toolu_abc" || tu.input.query !== "ai news") {
  console.log("[FAIL] tool_use payload field shape", JSON.stringify(tu));
  failed += 1;
} else {
  console.log("[OK] tool_use payload has name/toolUseId/input populated");
}

const tr = formatAnthropicAgents(asNode(cases[3].state)).sections.find(s => s.id === "block-0").payload;
if (tr.kind !== "tool_result" || !tr.content.includes("first") || !tr.content.includes("second") || tr.isError !== true) {
  console.log("[FAIL] tool_result list-content normalisation", JSON.stringify(tr));
  failed += 1;
} else {
  console.log("[OK] tool_result list-content normalised + isError=true");
}

if (failed > 0) {
  console.log(\`\\n*** \${failed} assertions FAILED ***\`);
  process.exit(1);
}
console.log("\\nR94 slice 3 smoke: ALL GREEN");
`;

const tmp = resolve(repo, ".r94-slice3-harness.mts");
import("node:fs").then(({ writeFileSync, unlinkSync }) => {
  writeFileSync(tmp, harness);
  const res = spawnSync("npx", ["tsx", tmp], {
    cwd: repo,
    stdio: "inherit",
    encoding: "utf8",
  });
  try { unlinkSync(tmp); } catch {}
  process.exit(res.status ?? 1);
});
