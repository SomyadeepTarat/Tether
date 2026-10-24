# Candidate engine interface v1

These contracts are proposed for teammate agreement, not silently declared final.
JSON Schema files in contracts/ are generated from engine/schemas.py.

## Intentional additions to PRD examples

AgentAction includes project_id so project identity can be checked directly.
Numerical claims use {value, reference_id, quote}; quote must be an exact fixture
summary substring appearing in output. Source records explicitly mark synthetic
data. Candidate schemas reject unknown fields. These decisions need full-stack
agreement before external API consumers depend on them.

## First slice

- Store.create_goal_contract(GoalContract): creates immutable initial v1.
- Store.start_session(project_id, session_id): creates an application-owned session.
- plan_next_action(client, contract, session_id, references, action_id,
  existing_sections): returns a typed, untrusted proposal; no write.
- validate_action(action, contract, session_id, references, existing_sections):
  returns ValidationResult, no write or model call.
- Store.commit_action(action, references): reloads authoritative contract and
  session; revalidates inside BEGIN IMMEDIATE; atomically persists decision,
  allowed artifact, audit event and checkpoint; returns StepResult.
- run_step(store, client, project_id, session_id, references, action_id): one
  genuine inference proposal followed by controlled commit. Repeated action key
  returns saved result with replayed=true without another model call.
- Store.restore_checkpoint(session_id): reloads current contract and persisted
  artifacts from SQLite, without conversation history.
- Store.sections(project_id), Store.timeline(project_id): read persisted outputs.

StepResult contains action, validation, committed, replayed. REVIEW and BLOCK
persist proposals and audit records but never write artifacts. A repeated key with
changed action content errors; action IDs are globally unique. A replay returns
its historical outcome; it does not execute against the current contract again.

The full-stack service must supply its own trusted fixture records and identities,
not accept client-provided references, contract state, validation decisions or
approval flags. Never call a model while holding a database transaction. Pending
inference recovery, production repository integration and request concurrency
coordination need a service-level implementation. Store uses one connection per
instance; do not share a connection across FastAPI worker threads.

## Validation limitations

Deterministic scope keyword rules are conservative examples, not complete semantic
classification. Exact quotation output is the narrow automatic path. New prose
requires REVIEW, even if plausible; review resolution is not yet implemented.
No model-based reviewer can downgrade BLOCK. The initial adapter intentionally has
no API for accepting a caller-provided ALLOW or overriding a blocked action.

## Provider update — 24 October 2026

Use `engine.llm_client.create_inference_client()` for Groq primary/Ollama backup.
The user authorized this change; no Jev is planned. Domain/StepResult schemas are
unchanged. The reference Store additionally emits provider attribution through
`record_inference(project, session_id, action_id, calls)`; mirror this when replacing
the repository adapter. See [the complete teammate update](../docs/TEAMMATE_UPDATE.md)
for failure routing, credentials, UI status and evaluation requirements.

## Lifecycle update

See [LIFECYCLE_UPDATE.md](../docs/LIFECYCLE_UPDATE.md) for additive goal-change,
execution-progress and specialist services. New schemas: GoalChange,
HandoffResult, WorkflowResult. Existing StepResult remains unchanged. The backend
must authenticate approval/completion actors; the engine does not authenticate
caller identity. Use effective_contract() for live milestone status and
contracts()/current_contract() for immutable approved history.
