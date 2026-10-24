# Pulled repository audit — 24 October 2026

Reviewed merged revision 9015fdc, the PRD context, engine contracts, backend routes,
persistence, dashboard and tests. The merged base suite passed 78 tests after
installing its declared backend/frontend dependencies into the local environment.

## Implemented gaps

- Explicit user resolution of REVIEW proposals. An explanation and backend-owned
  local operator identity are required. Current contract/version, sources, numbers,
  milestone authorization and report base revision are checked again inside the
  same transaction as artifact commit. BLOCK cannot be overridden. The original
  REVIEW is retained; a separate user approval is audited. Final decisions are
  idempotent and cannot be reversed.
- Proposal base revisions prevent delayed review approval from overwriting newer
  report content. Automatic proposals cannot overwrite another milestone's section.
- Source summaries are exposed only for approved topics and displayed beside the
  proposed content so a reviewer can inspect evidence before approving.
- Comparison and recommendation milestones may synthesize the supplied evidence;
  this prose requires human review. COST must include numerical evidence; a list
  of providers/citation IDs alone cannot be approved as a cost section.
- Uncertain/blocked specialist research can be explicitly rejected; this clears
  the pending step, preserves its history and allows a new proposal. An abandoned
  research key cannot be resumed. Research approval is not exposed.
- Approval, goal-change decisions, session creation and milestone completion keep
  active-work checks and writes under one lock. Nested engine transactions use
  SQLite savepoints. Model calls remain outside write transactions.
- Restore saved state is wired to the recovery API. Fresh demo creates a new v1
  project while preserving the original project, artifacts and audit history.
- Independent proposal evaluation CLI and persistent dashboard results replace the
  permanent metrics placeholder. Baseline and Tether use the same planner prompt,
  model/provider and token budget; only runtime enforcement differs. Baseline
  writes are simulated and never reach product artifacts. The grader does not
  import the runtime validator. Failed runs and uncertain factual support remain
  visible. Zero commits yield an undefined rate (N/A), not a perfect score.

Additive SQLite tables: action_bases, action_reviews, evaluation_runs. Existing
wire contracts and source fixtures were preserved. No existing user project was
reset or deleted.

## Verification

- Python suite: 95 passed, including engine, provider, lifecycle and HTTP tests.
- Frontend TypeScript check and production build: passed.
- Compile and diff whitespace checks: passed.
- Local production dashboard/API proxy opened successfully using an isolated
  runtime/pull-verification.sqlite3 database. Browser inspector showed real source
  evidence and validation details. A real Ollama proposal was BLOCKED; a retry
  produced an incomplete REVIEW proposal that was explicitly rejected in the
  browser. Its disposition persisted and the report stayed unchanged. The final
  validator now blocks cost placeholders without numerical evidence outright.
- Genuine local action replay returned the stored result without another model
  call. No success was fabricated from the rejected proposals.
- Two exploratory local evaluation batches (four calls each: clean/drift ×
  baseline/Tether) were recorded and displayed by the dashboard. The first used a
  source/authorization-only grader. Inspection exposed missing declaration checks;
  the second used grader v2 with those checks. The current v3 also rejects missing
  cost evidence. Versions remain labeled for comparability; do not pool these
  exploratory batches into a single quality score.
- The v2 batch detected undeclared numerical evidence/section-effect errors in
  baseline proposals; Tether blocked its proposals. No semantic scope drift was
  established and no improvement claim is justified by this small sample.
  Raw calls, timing/settings and original outputs are in runtime/evaluations/.

The installed Starlette/FastAPI stack emits one TestClient deprecation warning;
checks pass. Initial testing was local-only. The user then configured the Groq
key in the ignored root .env. The application previously did not read that file;
backend/factory/CLI now load it without overriding explicit environment values.
The local Python certificate store also failed verification; the adapter now uses
the certifi CA bundle (or SSL_CERT_FILE) with hostname/certificate checks enabled,
and sends an application User-Agent. No key is printed, committed or persisted.

A genuine Groq-only structured probe passed in 0.618 seconds. A report proposal
was BLOCKED for putting citation IDs inside evidence quotes; the next response
copied a historic action ID and was rejected. Instructions were clarified and
historical feedback now excludes obsolete application identities. A subsequent
real Groq-only report passed validation and committed in 1.115 seconds, with no
Ollama fallback. Replay in a fresh process committed nothing again and made no
provider call. These are smoke timings, not statistical performance guarantees.
The report test used the previously approved synthetic report payload and a
separate runtime/groq-primary-verification.sqlite3 database. Hosted specialist
inference was not attempted.

The API/frontend were restarted with the user's .env and workspace database.
The production proxy health confirms Groq primary, local backup, and enabled
human REVIEW resolution. Existing user projects were not reset or deleted.

## Limits and next work

This is not a completed four-session baseline evaluation. The evaluator covers
individual proposals, not long-run milestone completeness, handoff correctness or
recovery metrics. Arbitrary prose receives UNVERIFIED source fidelity; keyword
scope rules do not establish complete semantic correctness. Broader fixtures,
repeated matched multi-session runs, broader Groq model-quality testing, and
presentation charts remain. The local Qwen model still needs careful review:
schema-valid output does not guarantee useful or complete work.

Useful commands (from repository root):

```sh
.venv/bin/python -m pytest -q
cd frontend
npm run typecheck
npm run build
```

Measured evaluation (same project ID/database as the application):

```sh
PYTHONPATH=. .venv/bin/python scripts/evaluate.py --db backend/data/tether.sqlite3 \
  --project YOUR_PROJECT_ID --provider ollama --repeats 1
```

Use groq-only for separately authorized hosted measurement with a configured key.
