# Tether

Persistent goal enforcement across AI sessions. This merged version includes the Next.js dashboard, FastAPI product API and the updated Python engine: strict shared schemas, deterministic evidence validation, Groq primary/Ollama backup, immutable goal evolution, explicit milestone progression, checkpoints and sequential specialists.

## Run the application

Python 3.12+ and Node.js 20.9+ required. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8000/docs. Use a single backend worker; SQLite step claims serialize local execution. Backend grants a same-site HttpOnly local operator cookie on GET /api/health; mutations require that cookie and a trusted local Origin. Refresh the dashboard after restarting the backend. Agent output and arbitrary JSON cannot supply an approval actor.

## Provider configuration

FastAPI loads backend/.env and then the ignored root .env file. Explicit shell/service variables take precedence, then backend/.env, then root .env. The standalone engine CLI loads root .env. Restart FastAPI after editing credentials; .env.example contains placeholders only. Credentials never belong in NEXT_PUBLIC variables, tracked files or persisted events. Use a Groq Free plan account without enabling paid billing.

- TETHER_PROVIDER=groq (default): hosted primary with eligible-failure Ollama backup.
- TETHER_PROVIDER=groq-only: no fallback, for honest provider-only measurements.
- TETHER_PROVIDER=ollama: explicit offline mode.
- GROQ_API_KEY, GROQ_MODEL=openai/gpt-oss-20b, GROQ_TIMEOUT_SECONDS=15.
- OLLAMA_BASE_URL=http://127.0.0.1:11434, OLLAMA_MODEL=qwen3:4b.
- TETHER_DB=backend/data/tether.sqlite3; TETHER_API_URL optionally changes the frontend proxy target.

Start Ollama and run `ollama pull qwen3:4b` for local inference. The hosted timeout is an HTTP I/O timeout, not a total deadline. Inference outages/eligible rate limits can fall back; policy BLOCK/REVIEW never switches providers. Malformed hosted requests and refusals fail visibly. Both providers use the same engine gateway.

Hosted report requests send the objective, constraints, synthetic fixture and validation feedback to Groq. Specialist requests additionally contain research/handoff material; the UI uses the configured provider for both sequential specialists. Durable state stays in SQLite. Inference events contain only allowlisted provider/model/agent/timing/fallback fields, never raw prompts or credentials. Historical actions retain their original attribution.

## Product workflow

1. Click **New project** and choose **Your request** for a concise general AI draft, or **Cloud comparison** for the guided synthetic evidence demo. General requests use one agent and one response per proposal; they do not browse or verify current information. Cloud comparisons retain the existing Research + Report or single-agent workflow.
2. **Create & start workflow** creates the project and starts a persisted backend sequence. Research → validated handoff → report → validation → commit → milestone progression runs without repeated next-step clicks. Closing the browser does not stop execution.
3. Exact quotations can commit automatically. Milestones advance only when the committed artifact covers every required source. Comparison/recommendation always require substantive human REVIEW, even if the model returns quotations alone. Review sources and enter an explanation to approve; approval resumes the sequence automatically. BLOCK cannot be overridden. Rejection preserves history; resume requests a new proposal.
4. In **Action review**, the validation reason and agent rationale explain why a proposal needs attention. Enter an explanation to approve, reject, or **Request changes**. Request changes generates a new proposal using your feedback and preserves the rejected version.
5. **Pause after current step** allows an in-flight proposal to finish, then stops further work. **Resume workflow** resumes saved progress and failed action keys; it does not repeat completed commits. Incomplete evidence pauses explicitly and can be regenerated on resume.
6. Scope expansion remains explicit: **Add serverless comparison → Approve change** creates immutable v2/M5. Start/resume a workflow to perform the newly approved work.
7. Restarting FastAPI pauses an interrupted workflow; resume once to continue from persisted artifacts and handoffs. Existing manual step/session APIs remain available for diagnostics.

Both agents use `TETHER_PROVIDER`: Groq primary/Ollama backup by default, `groq-only` for hosted-only execution, or `ollama` for offline inference. Groq rate limits with a valid `Retry-After` of at most 45 seconds receive one automatic retry before eligible fallback; longer waits fail/fall back visibly. Provider waiting is shown in the workflow message and audit timeline. There is no unbounded retry loop or policy-triggered fallback. Hosted calls are serialized within the API worker. After a terminal 429, new clients share a cooldown for the provider’s Retry-After interval (60 seconds when absent), failing over or reporting the limit without another hosted request. This reduces repeated requests; it does not increase provider quotas. Cooldowns reset on backend restart. Run one API worker.

Evaluation reads persisted proposal-level baseline/Tether runs; it stays empty until the evaluation CLI records actual calls. SYNTHETIC_DEMONSTRATION fixture values are invented, not current cloud prices or deployment measurements. The supplied deployment descriptions do not establish a simplicity ranking; recommendations must state this evidence limitation.

## Existing data

Opening an old full-stack database creates a `.pre-engine.sqlite3` backup, archives its tables as legacy_*, and imports its approved goal history/project/session metadata. Previous actions/reports remain available at GET /api/projects/{id}/archive. They are not silently recommitted against the new fixture and validators. Initial execution status is re-established; the original snapshots remain in the archive. No reset or deletion is performed.

## Tests

```powershell
python -m pytest -q --basetemp=backend/data/pytest-run
cd frontend
npm run typecheck
npm run build
```

Tests use isolated SQLite databases and scripted HTTP/model doubles. They do not claim live model quality or baseline improvements. See docs/INITIAL_RESULTS.md for the partner's historical measurements.

## Engine tools and contracts

```powershell
python -m scripts.run_slice --provider ollama --action A-NEW
python -m scripts.run_slice --mode specialists --provider ollama --action A-SPECIALISTS
python -m scripts.benchmark --provider groq-only
python -m scripts.export_schemas
```

CLI defaults to TETHER_DB or runtime/tether.sqlite3. Runtime outputs are ignored by Git. The CLI may save raw inference request/response artifacts locally; the product timeline does not.

- shared/INTEGRATION.md and shared/contracts/: engine wire contracts.
- docs/TEAMMATE_UPDATE.md: provider-routing agreement.
- docs/LIFECYCLE_UPDATE.md: goal evolution, milestones and handoffs.
- backend/store.py: product metadata, safe legacy migration and engine Store adapter.
- frontend/: three-tab dashboard and typed API view models.

The Fresh demo control starts a clean project and retains the original project/history. Remaining: comprehensive semantic drift classification and a full multi-session independent evaluation suite (the current runner evaluates individual proposals), broader charts and presentation polish. No fabricated success or performance metrics.


## Measured proposal evaluation

Use an existing project ID and the same database as the backend. The runner tests
clean and drift-note inputs in baseline and Tether modes with identical planner
inputs/budget. Baseline commits are simulated in evaluation output only; they never
write to the product report. Actual model responses and raw settings are saved
under `runtime/evaluations/`. The dashboard reads persisted summaries after refresh.

```sh
PYTHONPATH=. .venv/bin/python scripts/evaluate.py --db backend/data/tether.sqlite3 \
  --project YOUR_PROJECT_ID --provider ollama --repeats 1
```

Use `--provider groq-only` for an authorized hosted benchmark with a configured key.
Automatic provider fallback is disabled for comparisons. Arbitrary prose is graded
UNVERIFIED rather than assumed correct. Unauthorized rate is N/A when nothing
commits. These are proposal simulations, not a completed four-session benchmark.

See [pull verification and changes](docs/PULL_VERIFICATION.md) for current findings.

See [automatic workflow verification](docs/AUTOMATIC_WORKFLOW.md) for the current UX and validation evidence.
