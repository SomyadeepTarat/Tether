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

FastAPI loads backend/.env and then the repository-root .env at startup. Explicit shell/service environment variables take precedence. Copy .env.example to .env and add GROQ_API_KEY locally, then restart FastAPI. The standalone engine CLI still uses its process environment; it does not load these files automatically. Credentials never belong in NEXT_PUBLIC variables, tracked files or persisted events. Use a Groq Free plan account without enabling paid billing.

- TETHER_PROVIDER=groq (default): hosted primary with eligible-failure Ollama backup.
- TETHER_PROVIDER=groq-only: no fallback, for honest provider-only measurements.
- TETHER_PROVIDER=ollama: explicit offline mode.
- GROQ_API_KEY, GROQ_MODEL=openai/gpt-oss-20b, GROQ_TIMEOUT_SECONDS=15.
- OLLAMA_BASE_URL=http://127.0.0.1:11434, OLLAMA_MODEL=qwen3:4b.
- TETHER_DB=backend/data/tether.sqlite3; TETHER_API_URL optionally changes the frontend proxy target.

Start Ollama and run `ollama pull qwen3:4b` for local inference. The hosted timeout is an HTTP I/O timeout, not a total deadline. Inference outages/eligible rate limits can fall back; policy BLOCK/REVIEW never switches providers. Malformed hosted requests and refusals fail visibly. Both providers use the same engine gateway.

Hosted report requests send the objective, constraints, synthetic fixture and validation feedback to Groq. Specialist requests additionally contain research/handoff material; the UI selects local specialists explicitly. Durable state stays in SQLite. Inference events contain only allowlisted provider/model/agent/timing/fallback fields, never raw prompts or credentials. Historical actions retain their original attribution.

## Product workflow

1. Create a cloud-comparison project and start a session.
2. Run a controlled step; the real engine generates a typed AgentAction and validates it before commit.
3. Exact supported quotations may ALLOW automatically. Arbitrary prose is REVIEW; hard violations BLOCK. Semantic review approval is not implemented, so the UI cannot bypass the engine. REVIEW can be rejected.
4. Confirm an active milestone complete only after inspecting its committed supporting artifact. This advances execution state without mutating approved contract snapshots.
5. Propose and approve SERVERLESS to create immutable contract v2.
6. Restart and restore checkpoints/current contract/artifacts. Reuse action_id on POST /api/sessions/{id}/step to replay without generation; interrupted specialist steps resume their validated handoff.

New sessions default to single agent. The UI also offers explicit local specialists. The engine's specialist function itself supports configured providers for separately authorized use. Evaluation remains an empty state until independent measured runs exist. SYNTHETIC_DEMONSTRATION fixture values are invented, not current cloud prices or deployment measurements. The narrow quotation report is not a finished recommendation.

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

Remaining: comprehensive semantic review resolution, independent baseline evaluation/charts, broader presentation polish and project-scoped demo reset. No fabricated success or performance metrics.
