# AI engine lifecycle integration — 24 October 2026

The Groq-primary/Ollama-backup plan is unchanged. This update adds engine services,
not FastAPI routes or a Next.js implementation. Candidate existing action/result
wire contracts remain compatible; new GoalChange, HandoffResult and WorkflowResult
JSON schemas are exported under shared/contracts/.

## Immutable goal evolution

`store.propose_goal_change(GoalChange)` persists a PENDING proposal and audit event.
Proposal fields: change_id, project_id, base_version, added_topics,
added_milestones, rationale. Proposed changes cannot replace old milestones,
modify constraints, duplicate IDs, authorize existing topics again, or declare
new work completed. This initial API supports additive scope expansion only.

`store.decide_goal_change(change_id, approve=True|False, actor=...)` records a final
user decision. The BACKEND must authenticate/authorize that actor; a nonempty
string is an integration assertion, not an authentication mechanism. Do not expose
this method as an agent tool or trust an actor from arbitrary request JSON.
Approval rechecks the current base version inside the transaction, appends a new
contract snapshot and records the decision atomically. Concurrent/stale approvals
cannot replace the latest contract. Repeated identical decisions are idempotent;
reversing a final decision is rejected. Rejected changes create no contract version.
For the PRD scenario, add SERVERLESS and pending milestone M5 through this service.

`store.contracts(project_id)` returns immutable approved snapshots in version order.
`store.current_contract(project_id)` returns the newest immutable snapshot.
`store.effective_contract(project_id)` overlays durable milestone execution status
without editing approved snapshots. Use effective_contract for live UI/planning.

## Explicit milestone progression

`store.complete_milestone(project_id, milestone_id, actor=...)` is a trusted
application/user confirmation, not an agent claim. It requires an active milestone
and a linked committed artifact that still exists, marks it complete, activates
the next pending milestone, and records the actor/supporting action IDs. Repeated
completion is idempotent. Completion does not change the contract version.
The human/application is responsible for confirming substantive completeness;
artifact presence alone does not independently prove the objective was fulfilled.
Approval of v2 preserves existing execution progress; M5 starts pending while
other work is active, or active if all previous work has finished.

## Sequential specialist workflow

`run_specialist_step(store, client, project_id, session_id, references, action_id)`:

1. Replays an existing action without inference if its key/session matches.
2. Generates Research Agent findings from authorized fixture records, or resumes
   the persisted handoff for this step.
3. Saves/revalidates the handoff against current identity, version, active
   milestone/topic, source ID/provider, and source quotations. Unknown sources,
   unauthorized topics or stale versions BLOCK; paraphrases/unresolved questions
   REVIEW. Neither outcome reaches Report Agent.
4. Generates a Report Agent proposal from the validated handoff and its sources.
5. Binds report identity/milestone/topic to the handoff and commits only through
   the existing validation gateway. References outside the handoff are rejected.
6. Persists audit, artifact and checkpoint state. No model can approve itself.

The report uses the same conservative quotation-only ALLOW path as before.
Comparison/recommendation milestones can access approved cost/deployment sources;
serverless evidence is excluded until it is approved. A meaningful free-form
recommendation still requires REVIEW; resolution remains future work.

WorkflowResult contains state, optional HandoffResult and optional StepResult.
COMPLETED means this controlled step committed, not that every project milestone
is done. HandoffResult includes handoff, validation and replayed.
A report can be absent when a handoff blocks or awaits review.

New reference store methods: save_handoff(..., action_id=...),
handoff_result(handoff_id), handoffs(session_id). The application derives
handoff_id as action_id + ':research'. Handoff IDs and action IDs remain distinct.
Saved handoffs are never trusted solely because an earlier version allowed them.
Changed decisions are persisted with HANDOFF_REVALIDATED audit events.

## Recovery and integration

Session creation now creates an IDLE checkpoint before inference. A validated
handoff saves pending_action_id, handoff_id and HANDOFF state before report
inference. After a crash, restore_checkpoint(session_id) returns current approved
contract/effective milestone status, artifacts and handoffs; run the same step key
to resume without repeating research. A completed/rejected step replays its
historical outcome without re-execution. An old pending handoff is revalidated
and BLOCKED if approval changed the active version.

Production backend adapters need the new lifecycle tables/services: changes,
milestone_state and handoffs, plus the existing checkpoints/audit events.
The reference Store creates these tables additively when opening old databases;
no demo reset or destructive migration is required. Keep per-thread SQLite and
inference-outside-write-transaction integration rules from TEAMMATE_UPDATE.md.
Serialize a session's step requests at the service layer; concurrent duplicate
model generation is not prevented by this reference engine, although artifact
commits remain idempotent. No model call automatically downgrades to single-agent
mode after a policy failure. Choose explicit single-agent mode for the required
operational fallback.

## Commands

```sh
# Default single-agent path stays compatible:
PYTHONPATH=. .venv/bin/python scripts/run_slice.py --action A-NEW
# Two sequential specialists, exclusively local:
PYTHONPATH=. .venv/bin/python scripts/run_slice.py --mode specialists --provider ollama \
  --db runtime/specialists.sqlite3 --session S-SPECIALISTS-001 --action A-SPECIALISTS-001
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python scripts/export_schemas.py
```

Inference audit attempts now also include an optional agent field (RESEARCH or
REPORT) for new calls. Older events remain compatible without it.

The deterministic suite uses scripted test doubles to exercise four persisted
sessions, drift rejection, v2 approval, interruption/restart and replay. These are
not model-quality evaluations or baseline comparisons. Live Groq specialist
verification is not claimed; the hosted specialist test was rejected by automatic
approval review because its research/handoff payload exceeded the previous
report-only approval. Local specialist verification avoids this export.

Next work: FastAPI/UI integration, review resolution, full benchmark/evaluation
harness and independent fixture grading. Do not present the current quotation
report as a finished recommendation or claim baseline improvement.

## Observed verification

65 deterministic tests passed. A real local Ollama run generated a three-provider
research handoff that passed validation, then a report proposal that passed the
action gateway and committed a synthetic cost section. This is a genuine
two-specialist local run, not a replay or scripted test. No hosted specialist
performance or four-session model evaluation is claimed.
