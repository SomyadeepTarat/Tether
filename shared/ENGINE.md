# AI engine integration agreement

The user-approved 24 October provider update supersedes the original Ollama-only requirement. Default: Groq Free with openai/gpt-oss-20b, backed up by local Ollama qwen3:4b. No paid billing or paid validator. Objective, constraints, synthetic fixture and validation feedback are authorized hosted inputs. Durable state stays in SQLite.

The engine package is not yet in this checkout. `backend/inference.py` imports `engine.llm_client.create_inference_client` when execution is requested and reports integration pending if absent. It does not recreate the teammate's routing logic. Until the shared engine schemas arrive, the temporary backend pipeline calls `client.generate(Proposal, system, prompt)` and keeps otherwise valid output at REVIEW. It does not claim the incoming engine's exact-quotation ALLOW behavior.

Full-stack owns frontend, HTTP routes, SQLite transactions, approvals and recovery. AI engineer owns agents, model adapter, handoff validation, action validation and independent evaluation. Coordinate schema changes.

Current Proposal fields: contract_version, milestone_id, topic, section_id, content, reference_ids_used, rationale. See the Pydantic model in backend/main.py and frontend/lib/types.ts. Migrate together to the full PRD AgentAction (identity, action type, declared effects and numerical claims).

## Integration flow

1. Backend loads current contract, milestones and committed artifacts.
2. Engine runs research -> validates handoff -> generates report proposal -> validates action.
3. Engine returns typed results. Agents never write SQLite directly.
4. Backend persists findings, handoffs, proposals, validation and checkpoint state.
5. Executor commits only ALLOW actions or explicitly approved REVIEW actions. Recheck contract version inside the commit transaction. Action ID is the unique commit key.

Temporary validation checks schema, active version, milestone/topic, source ID existence and synthetic label. It does not verify numerical claims or detect hidden semantic drift. Otherwise valid proposals therefore require human review. Deterministic BLOCK cannot be approved. This gateway must be replaced by the supplied run_step pipeline once the engine is pushed.

Current recovery derives milestone progress from committed artifacts. Add full checkpoints and agent state for the specialist workflow. Handoff and evaluation endpoints return explicit empty states pending integration. Do not fabricate metrics or enable automatic ALLOW until mandatory validation exists.

## Incoming integration checkpoint

Use the incoming `shared/contracts/` and `shared/INTEGRATION.md` as the schema agreement; neither exists here yet. Adapt backend repositories to the actual Store protocol and call `run_step(store, client, project_id, session_id, references, action_id)`. Do not guess GoalContract/AgentAction wire fields or reference-store table layouts. Existing sync FastAPI handlers run in a worker thread, and each SQLite connection is created/used within that thread. Inference happens outside write transactions.

`record_inference(project, session_id, action_id, calls)` persists an INFERENCE_COMPLETED event before policy outcome, including failed attempts before propagating errors. Event body contains session_id, action_id, attempts; attempt fields are explicitly allowlisted and credentials are redacted. No raw prompt or API response is saved. Historical action attribution comes from these events, never current configuration. Old actions with no telemetry show unknown attribution.

Preserve the engine's semantics: missing key/auth/network/408/429/498/5xx or two invalid responses may fall back. HTTP 400/404/413/422 or refusals fail visibly. Never fail over due to a policy BLOCK. groq-only forbids fallback. Do not retry/sleep on rate limits. Hosted timeout is HTTP I/O, not a total deadline. These behaviors belong to the incoming router and remain unverified here.
