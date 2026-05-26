# builtin-minimal demo

The `builtin-minimal` demo is the **zero-dependency, zero-API-key** record + fork pair
loaded by `chronos quickstart`. It seeds a fresh `chronos.db` with:

- **Parent run** `11111111-…-1111` (3 nodes: `greet → draft → finalize`, friendly tone).
- **Child run** `33333333-…-3333` forked at `greet` with `tone="formal"`, re-running
  `draft → finalize` to produce a different output.
- **Fork edge** linking the two with `edited_fields={"tone": "formal"}`.

After loading you can immediately run:

```bash
chronos runs list                  # 2 runs visible
chronos diff 11111111-…-1111 33333333-…-3333   # see the tone+draft diff
chronos web                        # explore in the browser
```

## Format

`envelopes.jsonl` is a quickstart-internal demo format (NOT the
`tests/golden/<adapter>/<scenario>/envelopes.jsonl` golden-trace contract — that
contract is documented in `docs/contracts/golden-trace-format.md` and is consumed by
`chronos verify-golden`, not by `chronos quickstart`).

Each line is a JSON object with exactly one top-level key:

| Key       | Meaning |
|-----------|---------|
| `_meta`   | (Optional) human-readable header. Ignored by the loader. |
| `_run`    | Run record. Run is `put_run`'d before its nodes appear. |
| `node`    | Node record. `run_id` must reference a previously-declared `_run`. |
| `_fork`   | Fork edge. Parent + child runs must already exist. |

Field names match `chronos.core.models.{Run,Node,Fork}`. Timestamps default to
deterministic synthetic values inside `quickstart.py` (so the demo's `started_at`
is reproducible across invocations).

## Authoring more demos

Drop `examples/<your-name>/envelopes.jsonl` in the same shape and load with
`chronos quickstart --demo <your-name>`. The R115-R117 docs-and-demo track will
ship 2 more demos (`linear-pipeline-trace` and `router-loop-trace` derived from
the existing `examples/linear_pipeline.py` / `examples/router_loop.py`) so the
R120 acceptance row "≥3 real demo runs" lands.
