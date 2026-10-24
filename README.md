# Tether

Goal-alignment workspace: Next.js, TypeScript, Tailwind, FastAPI and SQLite. Updated inference plan: Groq Free primary, Ollama backup or explicit offline mode.

## Run locally

Python 3.12 and Node.js 20.9+ required. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:3000. API documentation: http://127.0.0.1:8000/docs.

The AI teammate will push the engine separately; generation currently reports integration pending. Backend configuration: TETHER_PROVIDER=groq (default), GROQ_API_KEY, GROQ_MODEL=openai/gpt-oss-20b, GROQ_TIMEOUT_SECONDS=15, OLLAMA_BASE_URL=http://127.0.0.1:11434 and OLLAMA_MODEL=qwen3:4b. groq-only disables fallback; ollama selects local inference. Never put credentials in NEXT_PUBLIC variables or tracked files. Use a Groq Free account without paid billing. Env files are not automatically loaded. TETHER_API_URL changes the Next.js proxy target.

When Groq is selected, objective, constraints, synthetic fixture and previous validation feedback leave the machine; SQLite project state remains local. The dashboard shows this and displays historical provider/model/fallback telemetry. Live Groq behavior is not yet verified in this checkout.

## Workflow

Create a cloud-comparison project, start a session, and run its next step after engine integration. Inspect the real model proposal under Drift inspector. Approve or reject REVIEW actions; hard BLOCK cannot be approved. Accepted sections appear in the report. Propose and approve serverless scope to create immutable contract v2. Restart services to restore saved progress.

Reference values are SYNTHETIC_DEMONSTRATION, not real cloud prices. The initial template has cloud-comparison milestones even if objective wording is edited.

## Layout and ownership

- frontend/app: three-tab dashboard and responsive theme.
- frontend/lib: typed API and frontend models.
- frontend/components/ui: reusable controls.
- backend/main.py: application routes, SQLite transactions and temporary proposal pipeline.
- backend/inference.py: incoming engine factory boundary and sanitized provider telemetry.
- scenarios/cloud_snapshot.json: illustrative evidence fixture.
- shared/ENGINE.md: AI teammate integration agreement.

Implemented: projects, immutable contracts, sessions, engine client integration boundary, structural validation, review/commit/reject, serverless approvals, report artifacts and audit history. SQLite persists progress; unique action IDs prevent duplicate commits. Failed inference is FAILED; policy rejection is BLOCKED. Inference telemetry persists before the action outcome, including failures.

Remaining: full PRD engine schemas, evidence/content validators, specialist handoffs, expanded checkpoints, independent evaluation, benchmark charts and demo reset. All proposals require human review until full validation is integrated. No fabricated evaluation results. Current controls use custom components; broader shadcn, Recharts and Motion integration remains for screens that need them.

## Checks

```powershell
python -m unittest discover -s tests -v
cd frontend
npm run typecheck
npm run build
```
