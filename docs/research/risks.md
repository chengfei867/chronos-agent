# Risk Register

**Last updated**: 2026-04-22 (Round 1)
**Review cadence**: Updated every round; full review at end of each phase.

> Every risk gets: description, likelihood (H/M/L), impact (H/M/L), mitigation, trigger (when does it matter).

---

## Technical Risks

### R-T1. Fork re-execution is non-deterministic enough to be useless
- **Likelihood**: Medium
- **Impact**: High (kills core value prop)
- **Description**: Even with seed + temp=0, LLM outputs drift across calls. If "compare fork to original" always shows noise diffs, the diff view becomes unreadable.
- **Mitigation**:
  - Record model version + seed + all sampling params; warn user on model drift
  - Diff view highlights "structural" changes vs. "surface noise" (token-level vs. intent-level)
  - Offer LLM-as-judge semantic diff as premium option
- **Trigger to reopen**: First dogfood session shows noise >30%

### R-T2. LangGraph checkpointer is brittle for complex state
- **Likelihood**: Low-Medium
- **Impact**: Medium (delays v0.1)
- **Description**: Checkpointer pickles Python state; complex objects (DB connections, lazy loaded resources, custom classes) may not round-trip.
- **Mitigation**:
  - Start with agents that use only serializable state
  - Document state constraints in docs/limitations.md
  - Contribute upstream fixes to LangGraph if we find common issues
- **Trigger**: Spike 1 fails

### R-T3. Cross-framework adapter pattern leaks too much
- **Likelihood**: Medium
- **Impact**: Medium (slows v0.2 roadmap)
- **Description**: Each framework's state model is different enough that the "canonical event" format can't cover all use cases.
- **Mitigation**:
  - Use discriminated union in payload (per-kind + framework-specific fields allowed)
  - Tier adapters: Tier-1 (full R3) vs. Tier-2 (R1+R2+R4 only)
  - Document what's lossy per adapter
- **Trigger**: AutoGen adapter uncovers >3 semantic conflicts with LangGraph adapter

### R-T4. OTel GenAI spec churn
- **Likelihood**: Medium
- **Impact**: Low-Medium (refactor cost)
- **Description**: OTel agent semconv is "experimental" through 2026. Spec changes could invalidate our schema.
- **Mitigation**:
  - Keep our internal schema decoupled from OTel (adapter-in)
  - Version our schema; maintain compat layer
- **Trigger**: OTel publishes breaking change

### R-T5. Streaming LLM responses break node representation
- **Likelihood**: Medium
- **Impact**: Low
- **Description**: Most LLM calls today are streaming. A "node" may represent a stream, not a point.
- **Mitigation**: Normalize streams to final message; record delta if user opts in
- **Trigger**: Rarely — decide in v0.1 design phase

### R-T6. Performance: fork-with-UI takes >30s for simple cases
- **Likelihood**: Low
- **Impact**: Medium (hurts UX)
- **Description**: Each LLM call has 1-10s latency; a 5-step re-execution is 5-50s.
- **Mitigation**:
  - Parallelize what can be parallelized
  - "Streaming re-execution" UX — show partial results
  - Cache at tool-output level where deterministic
- **Trigger**: v0.1 dogfood shows >30s for 5-node fork

---

## Product / Market Risks

### R-P1. No paying customers because the ICP doesn't exist yet
- **Likelihood**: Medium-High
- **Impact**: High (commercial failure, not technical)
- **Description**: Multi-agent systems are 2026 nascent; most dev teams haven't gotten to "needs time-travel debugging" yet.
- **Mitigation**:
  - Accept: v0.1-v0.3 = OSS community-first, no monetization pressure
  - Dogfood: be the main user (Hermes Agent uses it daily)
  - Secondary ICP: AI researchers running experiments (academic market)
  - When teams grow into the need, chronos-agent is already the standard
- **Trigger**: N/A — this is an accepted strategic bet

### R-P2. LangSmith / LangGraph absorbs the feature
- **Likelihood**: Medium
- **Impact**: High (market takeover)
- **Description**: LangGraph already has checkpointer — they could ship a UI and call it done for their ecosystem.
- **Mitigation**:
  - **Cross-framework** is the moat — LangChain won't support AutoGen properly
  - Open-source ethos — we are the neutral tool; LangSmith is captive
  - Speed — we ship before they do
- **Trigger**: LangChain announces "LangSmith Time-Travel" or similar

### R-P3. A well-funded startup launches with more resources
- **Likelihood**: Medium (YC batches, a16z / Sequoia targets)
- **Impact**: Medium-High
- **Mitigation**:
  - Open source moat (community > cash in early tool wars)
  - The "100% AI-built" angle is unique and marketable
  - Be faster; be deeper in the specific niche
- **Trigger**: ProductHunt / TechCrunch announcement of a competing startup

### R-P4. Developers prefer their framework's native tooling
- **Likelihood**: Medium-High for LangChain users
- **Impact**: Medium
- **Mitigation**:
  - Ensure first-adapter experience (LangGraph) is SIGNIFICANTLY better than native
  - Win on diff/fork (things LangGraph will never ship)
- **Trigger**: User interviews (post v0.1) say "native is enough"

### R-P5. The "time-travel" metaphor doesn't click
- **Likelihood**: Low-Medium
- **Impact**: Medium
- **Description**: Users might not understand "fork at step N" or might find the tree UI overwhelming
- **Mitigation**:
  - Very clear tutorials with worked examples
  - Entry point: "Why did my agent cost $80?" → fork to find the expensive branch
  - Entry point: "Did my prompt change break anything?" → fork old vs. new, diff results
- **Trigger**: First 10 users don't understand

---

## Operational / Project Risks

### R-O1. AI developer (Hermes Agent) loses project context between rounds
- **Likelihood**: Medium-High (this is the core project risk)
- **Impact**: High (project goes off-rails)
- **Description**: Cron rounds are stateless; agent must re-onboard each time. If CONTEXT.md or progress docs are weak, agent rebuilds wrong mental model.
- **Mitigation**:
  - `docs/CONTEXT.md` is the sacred onboarding doc — maintained rigorously
  - Every round ends with `progress/YYYY-MM-DD-HHMM.md` covering decisions, rationale, next steps
  - Every ADR captures decision boundaries so the agent doesn't rethink them
  - **Never** delete docs — append or supersede
- **Trigger**: A round makes a decision contradicting a previous ADR

### R-O2. Cron fails silently (missed round, stuck process, bad creds)
- **Likelihood**: Medium
- **Impact**: Medium (gap in progress, no harm)
- **Mitigation**:
  - Each cron execution writes progress doc with timestamp; gaps are visible
  - Cron env tests GitHub push early in round
  - Human user can run a manual round ad-hoc if missed
- **Trigger**: 2+ consecutive rounds without progress doc

### R-O3. GitHub push fails due to mirror outage
- **Likelihood**: Medium
- **Impact**: Medium (commits staged locally but not pushed)
- **Description**: Primary mirror `gh-proxy.com` may be down; direct GitHub is blocked
- **Mitigation**:
  - Try `gh-proxy.com`, fallback to alternates; document working set
  - Keep local `.git` pristine; re-try next round
- **Trigger**: Current mirror returns error

### R-O4. LLM API outage / quota for Hermes Agent
- **Likelihood**: Low-Medium
- **Impact**: High (agent can't think)
- **Description**: The baidu-int Claude Opus 4.7 proxy could be down or out of quota
- **Mitigation**:
  - Accept: human instigator restarts / refills quota when this happens
  - Document in progress doc as `BLOCKED: LLM API`
- **Trigger**: Repeated 429/500 from API

### R-O5. Scope creep
- **Likelihood**: Medium-High
- **Impact**: Medium
- **Description**: Each round the agent is tempted to add "just one more framework adapter" before v0.1 ships
- **Mitigation**:
  - Roadmap has hard phase gates
  - ADR before adding a framework
  - progress doc asks "did I stay in this round's scope?"
- **Trigger**: v0.1 scope grows >50% after Phase 0 exit

---

## Legal / Compliance / Ethical Risks

### R-L1. Telemetry data leakage via traces
- **Likelihood**: Medium if others use chronos-agent
- **Impact**: High (user prompts may contain sensitive data)
- **Description**: Storing full prompt + response as trace means any secret the user sent to the LLM is now in trace DB
- **Mitigation**:
  - **Local-first by default** — no trace leaves user machine without explicit opt-in
  - Redaction API — user declares PII patterns to scrub
  - Encryption at rest for trace DB (document, not default in v0.1)
- **Trigger**: Always applies

### R-L2. License conflicts
- **Likelihood**: Low
- **Impact**: Medium
- **Description**: If we use GPL deps, our MIT license is poisoned
- **Mitigation**:
  - Audit dependencies per adapter
  - Prefer MIT/Apache/BSD; isolate any GPL to plugin boundary
- **Trigger**: New dependency added

### R-L3. Using OpenAI/Anthropic APIs in docs/examples could violate TOS
- **Likelihood**: Low
- **Impact**: Low
- **Mitigation**: Use user-provided keys only; no bundled API access
- **Trigger**: N/A

### R-L4. "100% AI-generated" claim is legally fuzzy (copyright, liability)
- **Likelihood**: Low (for internal/private tool); Medium if productized
- **Impact**: Low-Medium
- **Description**: AI-generated works have unclear copyright status in many jurisdictions; may affect licensing/commercialization
- **Mitigation**:
  - README notes the AI-origin explicitly
  - MIT license disclaims warranty (standard)
  - Human user (chengfei867) is the repo owner / legal responsible party
- **Trigger**: Commercialization decision

### R-L5. Data from traces used for re-training (hosted variant)
- **Likelihood**: N/A for local-only; would apply if we go SaaS
- **Impact**: High (trust breakage)
- **Mitigation**: v0.1 is local-only, no question. If SaaS: clear DPA, no training.
- **Trigger**: SaaS decision

---

## Business Model / Strategic Risks

### R-B1. No sustainable business model
- **Likelihood**: Medium-High
- **Impact**: Low (tool is useful regardless)
- **Description**: Developer tools commonly struggle; devs don't pay for most tools
- **Mitigation**:
  - Accept: early phases = no revenue, OSS goodwill only
  - Future options: team features, cloud-hosted trace storage, enterprise support
  - Explicit non-goal for v0.1-v0.3: revenue
- **Trigger**: v1.0 milestone

### R-B2. Not monetizable because of local-first ethos
- **Likelihood**: Medium
- **Impact**: Low
- **Mitigation**: Local-first core + optional cloud SaaS for team features (standard pattern: Sentry, Grafana)

---

## Top 5 Most Important Risks to Watch

1. **R-O1** — Agent context loss (the whole project approach depends on doc discipline)
2. **R-T1** — Fork non-determinism (the core technical bet)
3. **R-P2** — LangGraph absorbs feature (the main competitive threat)
4. **R-L1** — Trace data leakage (blocks adoption if wrong)
5. **R-T2** — LangGraph checkpointer brittleness (blocks v0.1 if bad)

---

*Document owner: Hermes Agent. Revisit each round. Any new risk discovered must be added here.*
