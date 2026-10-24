# Tether PRD context and AI engineering scope

Source: Tether_Final_PRD_v4.pdf, all 14 pages, including Appendices A-C.

User-approved override (24 October 2026): use Groq primary inference with Ollama
backup; no Jev. The Ollama-only/no-cloud-inference requirement below describes the
original PRD. See TEAMMATE_UPDATE.md for the current provider plan. All remaining
authorization and product requirements still apply.
The cover and requirements say v4.0; some embedded footers still say v3.0.
The v4.0 requirements govern this implementation.

## Product and authority

Tether preserves an authorized objective outside model conversation history and
validates proposed actions before they can change committed report artifacts.
The application owns authorization, contract versions and durable state. Agents
cannot approve themselves, change goals, or bypass deterministic BLOCK results.
ALLOW passes mandatory checks; REVIEW needs resolution; BLOCK fails a mandatory
check. Optional semantic review can escalate uncertainty, never override BLOCK.

## Demonstration and evidence

Compare AWS, Azure and GCP for a small startup, prioritizing cost and deployment
simplicity using supplied reference data only. Every invented value is labeled
SYNTHETIC_DEMONSTRATION. Expected grading outcomes stay outside model-visible
fixtures. Demonstrate four sessions: initial research/report, injected enterprise
security/compliance drift, explicitly approved serverless goal expansion to v2/M5,
and context-cleared restart recovery with no duplicate commits. The two specialists
run sequentially on one local model. Single-agent fallback is mandatory.
Show genuine local inference and persisted artifacts. Label recorded replays.

## Ownership and integration

AI engineer owns engine schemas, local adapter, planner/agents, validation,
handoffs, controlled execution interfaces, goal evolution, scenario fixtures,
evaluation and engine tests. Full-stack engineer owns Next.js/TypeScript/Tailwind/
shadcn UI, FastAPI routes, production SQLite repositories, sessions/checkpoints,
approval UI, audit timeline and charts. Both agree shared contracts and integration.
No paid inference, cloud services, vector database or orchestration framework.
Python 3.12, Pydantic and pytest; benchmark Qwen3:4B through Ollama first.

Full-stack UI: Command Center, Drift Inspector, History & Evaluation as three tabs;
navy/slate with mint, amber review and red block. Show real state, separate proposed
from committed artifacts, no fake metrics or dead buttons. States: IDLE, PLANNING,
HANDOFF, VALIDATING, AWAITING_REVIEW, EXECUTING, COMPLETED, BLOCKED, FAILED.

Required APIs: create/read projects, contract history, start/read/step sessions,
handoffs, action decisions, propose/decide goal changes, timeline, report, metrics,
and demo reset. The PRD lists exact routes in section 7. Candidate JSON schemas
live in shared/contracts; they require agreement with the teammate before freezing.

## Sequencing and acceptance

First: benchmark, schemas, fixture, one genuine report proposal, validation,
transactional commit/rejection and restart recovery. Integrate it with FastAPI/UI
before expanding to specialist agents. Then immutable approved goal versions,
research/report handoffs, four-session scenario and fair baseline evaluation.
Hour checkpoints: 6 vertical slice; 10 versioning/approvals; 14 specialists or
fallback; 18 four sessions; 21 measured results; 24 live inference/recovery demo.

Persist projects, contracts, milestones, sessions, checkpoints, handoffs, proposals,
decisions, findings, artifacts, approvals, audit events and benchmark results.
The initial reference engine adapter persists only the subset needed by its slice.
Do not treat its schema as the complete production backend migration.

Evaluation must compare the same model, task, fixture, tools and comparable context
budget with/without independent enforcement; do not weaken baseline. Independently
grade unauthorized committed actions and sections, hard violations, milestone
completion, source fidelity, active-version compliance, recovery, handoff validity
and overhead latency. Keep deterministic tests separate from model performance.
Target 3-4 end-to-end runs per mode if feasible. Save raw data/settings/failures;
never invent improvement. Slow or unreliable specialists fall back to one agent.

## Current boundary

The initial engine runs one controlled report action, not the complete product.
It uses a conservative quotation-only ALLOW path; arbitrary prose is REVIEW.
Research handoffs have a candidate schema but no specialist runner yet. Goal-change
approval, semantic review resolution, milestone advancement, full session state
machine and independent baseline evaluation remain future integration work.
A successful section commit does not mark its entire milestone completed.
