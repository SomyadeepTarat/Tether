# Tether implementation update for the full-stack agent

Latest follow-up: see PULL_VERIFICATION.md for human review, evaluation, automatic
root .env loading and verified live Groq report execution. Earlier setup/verification
status below is historical.

Follow-up: engine lifecycle services are now implemented; read LIFECYCLE_UPDATE.md
for goal changes, milestone progress, handoffs and new integration methods.
The provider plan in this document remains current.

User-approved plan change — 24 October 2026. This supersedes the PRD's
Ollama-only/no-cloud-inference requirement. Other product and authorization
requirements remain in force. Do not implement Jev or another paid validator.
The user also explicitly approved sending objective, constraints, synthetic source
fixture and previous validation feedback to Groq for live report inference.

## Inference plan

- Primary: Groq hosted API, default model `openai/gpt-oss-20b`, strict JSON Schema
  structured output and low reasoning effort. Use a Groq Free plan account; do not enable paid billing.
- Backup: local Ollama, `qwen3:4b`. Explicit offline mode remains supported.
- Backend configuration: `TETHER_PROVIDER=groq` (default), `GROQ_API_KEY`,
  `GROQ_MODEL`, `GROQ_TIMEOUT_SECONDS=15`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.
- `TETHER_PROVIDER=groq-only` disables fallback for honest Groq-only benchmarks;
  `TETHER_PROVIDER=ollama` explicitly runs local inference.
- Credentials stay in the backend environment, never in Next.js client code,
  `NEXT_PUBLIC_*`, persisted events, or tracked files. `.env.example` is a template;
  the engine does not automatically load .env files.
- Inference payloads include objective/constraints, supplied fixture content and
  previous validation feedback. These inputs leave the machine when Groq is
  selected. Durable project state remains in SQLite.

## Failover semantics

`create_inference_client()` returns the configured provider/router; both providers
implement `generate(schema, system, prompt) -> Pydantic model` and expose `calls`.
Groq uses its hosted chat-completions endpoint; Ollama remains localhost-only.
The router falls back on missing key, authentication/access failures, network/
timeout errors, HTTP 408/429/498/5xx, or two locally detected invalid structured
responses. It immediately switches rather than sleeping/retrying a rate limit.
The 15-second Groq setting is an HTTP I/O timeout, not a guaranteed total deadline.
HTTP 400/404/413/422 and provider refusal fail visibly without fallback.
If both providers fail, propagate an error; no fabricated proposal or success.

CRITICAL: a schema-valid action that violates a goal is NOT an inference failure.
It goes through normal validation and persists BLOCK/REVIEW. Never switch models
merely to get an ALLOW. All providers use the same deterministic gateway/executor.

## Goal and validation layer

Keep Pydantic and SQLite authoritative for goals, immutable approved versions,
constraints and approvals. No Jev. Mandatory checks remain deterministic:
project/session identity, active contract, active milestone/topic, source IDs,
numerical evidence, declared section effects and synthetic-data labeling.
The first slice automatically allows exact supported quotations. Arbitrary prose
requires REVIEW; review resolution and comprehensive semantic evaluation are not
implemented yet. Do not label keyword rules as complete semantic enforcement.

## Backend integration

Import `create_inference_client` from `engine.llm_client`. Inject it into
`run_step(store, client, project_id, session_id, references, action_id)`.
The existing candidate GoalContract/AgentAction/AgentHandoff/ValidationResult/
StepResult wire schemas are unchanged by this provider switch. Continue using
`shared/contracts/` and `shared/INTEGRATION.md` for teammate agreement.

The reference Store now provides
`record_inference(project, session_id, action_id, calls)` and emits a persisted
`INFERENCE_COMPLETED` timeline event, before recording the action outcome.
Its body has session_id, action_id and attempts[]. Each attempt has provider,
model, started_at, attempt, schema_valid, elapsed_seconds and optional error_kind,
http_status, fallback_from, fallback_reason. No credentials/raw prompt are included.
The event means inference attempts ended, not that inference or execution succeeded.
On total inference failure, attempts are still recorded before the error propagates.
Mirror this event/method when replacing the reference store with backend repositories.

UI: display actual provider/model and an Ollama fallback indicator with reason.
Show failed inference as FAILED, not BLOCKED; BLOCKED is an action-policy outcome.
A replayed committed action must not generate again. Preserve its historical
provider attribution; do not relabel old Ollama actions as Groq.
Call synchronous inference off FastAPI's event loop and outside database write
transactions. The reference SQLite connection is thread-affine: instantiate/use
it inside the same worker thread or replace it with the backend's repository layer.

## Current status and next checkpoint

The working first slice includes strict schemas, synthetic cloud fixture, planner,
validator, controlled executor, SQLite artifacts/checkpoints/audit and replay.
Provider-routing tests cover success, outages, 429, invalid JSON, both providers
failing, no key leakage, no policy-driven failover, restart and replay.
GROQ_API_KEY is absent in the AI-engineer session: live Groq generation/latency is
unverified. Hosted request structure/routing are tested with mock HTTP responses.
Live verification: missing-key fallback passed a real structured probe (2.713 s),
and Ollama generated a real report section (13.355 s) that passed validation and
committed. A fresh process replayed it without inference. Provider/fallback
attribution survived restart. These are Ollama fallback measurements, not Groq
performance. All 40 tests pass.

Next full-stack checkpoint: create project/session, call the engine step, display
its real persisted action/validation/report plus provider/fallback status, restart
and recover without duplicate commit. Next engine work after integration includes
goal-change approval/versioning, milestone transitions, specialist handoffs,
review resolution and independent baseline evaluation.

Evaluation: compare baseline/Tether with the same provider, model, fixture and
comparable budget. Log actual model/version and fallback. Separate fallback runs
from provider-only results; do not silently compare Groq with Ollama or claim
unmeasured speedups. Original Ollama measurements remain historical evidence.
