# Hackathon review demo — 24 October 2026

Open http://127.0.0.1:3000. Both frontend and backend are running. Keep the backend
terminal running. Refresh the browser once to renew its local operator cookie.

Verified now: 104 tests passed; frontend typecheck passed; actual report inference
through the Next.js proxy used Groq openai/gpt-oss-20b. A genuine invalid proposal
was BLOCKED, then a corrected proposal was ALLOWED and committed. The successful
inference attempt took 0.760 seconds. Approved v2, checkpoint recovery and replay
without duplicate commit also passed. This is a smoke check, not a performance
benchmark or completed multi-session model evaluation.

## Reliable 3-minute presentation

1. Select **Hackathon review — rehearsed** in the Active project selector.
   Say: “Tether keeps an authorized goal outside the model's conversation and
   checks proposed work before it can change the report.” Show the goal,
   milestones, one committed report section and actual Groq provenance.
2. Open **Action review**. Select the earlier BLOCK proposal, show its actual
   validation reasons and declared effects, then the ALLOW proposal. Say:
   “The first real proposal failed validation. It did not write the report.
   The corrected proposal passed.” These are genuine rehearsed runs; don't call
   replayed history a new live call or call every validation failure semantic drift.
3. Return to **Overview**. Click **Fresh demo**; it creates a new v1 project and
   preserves the rehearsed project. Leave mode at **Single report agent · configured
   provider**, click **Start session**, then **Run next step** for live inference.
   If BLOCKED, inspect the explanation and run once more. If REVIEW, inspect source
   summaries and approve only if the content is useful, supported and within scope;
   enter at least ten characters explaining why. Otherwise reject it. Do not
   repeatedly retry during the review; switch to the prepared project if needed.
4. Show **Add serverless comparison → Approve change** after resolving any pending
   review. Open **History & evaluation** and show v1/v2: authorized goal evolution
   is explicit and old versions remain preserved. The prepared project already
   contains both versions if you need to skip the live approval.
5. Return to Overview, **Restore saved state**, then refresh. The contract/report
   stay persisted. Explain idempotency: replaying the same action key returns its
   existing outcome without another write. A page refresh alone is not a backend
   process restart; don't describe it as one.

## Short answers

- Generator: Groq primary; local Ollama backup. Current UI specialists use local
  Ollama explicitly, so use single-agent Groq mode for the shortest live demo.
- Enforcement: Pydantic plus deterministic checks of identity, active contract,
  milestone/topic, sources, numerical evidence and declared effects. An LLM cannot
  override BLOCK. Synthesized prose needs explicit human review.
- Persistence: SQLite stores immutable contract history, progress, handoffs,
  proposals, decisions, artifacts, checkpoints and provider/audit records.
- Two agents: the sequential Research → handoff gateway → Report path is implemented
  and tested. Avoid switching to it on stage unless local Ollama is ready.
- Evaluation: real proposal-level baseline/Tether evaluation is implemented.
  Full multi-session comparative evaluation and comprehensive semantic correctness
  are still incomplete. No measured improvement claim is justified yet.
- Prices: every fixture value is SYNTHETIC_DEMONSTRATION, not current cloud pricing.

## If a service stops (macOS)

Backend terminal:

```sh
cd /Users/somyadeeptarat/Desktop/Tether
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal:

```sh
cd /Users/somyadeeptarat/Desktop/Tether/frontend
npm run start -- --port 3000
```

Refresh the dashboard after restarting the backend. The .env key remains local;
show the app and provenance rather than opening credentials on the projector.
