# Tether

Persistent goal enforcement for multi-session agents. Inference now uses Groq
first, with local Ollama backup. Goals, validation and durable state remain in
application code and SQLite. The initial engine slice is implemented; the
FastAPI/Next.js product is not implemented yet.

See the [teammate plan update](docs/TEAMMATE_UPDATE.md),
[PRD context](docs/PRD_CONTEXT.md), and [candidate interface](shared/INTEGRATION.md).
The user-approved provider change supersedes the PRD's Ollama-only requirement.

## Setup

Requires Python 3.12+. Install Ollama and `qwen3:4b` for local backup.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
ollama serve
# In another terminal, if the model is not installed:
ollama pull qwen3:4b
```

Set `GROQ_API_KEY` in the backend environment using a Groq Free plan account;
do not enable paid billing. Never put the key in client-side Next.js variables.
`.env.example` documents configuration but is not loaded automatically.
The model default is `openai/gpt-oss-20b`; set `GROQ_MODEL` to override it.

```sh
# Default: Groq first, Ollama backup. Missing key is recorded and uses backup.
PYTHONPATH=. .venv/bin/python scripts/run_slice.py --action A-NEW-001
# Explicit offline mode:
PYTHONPATH=. .venv/bin/python scripts/run_slice.py --provider ollama --action A-NEW-002
# Compare providers without hiding fallback in results:
PYTHONPATH=. .venv/bin/python scripts/benchmark.py --provider groq-only
PYTHONPATH=. .venv/bin/python scripts/benchmark.py --provider ollama
.venv/bin/python -m pytest -q
```

`TETHER_PROVIDER` accepts `groq` (default router), `groq-only`, or `ollama`;
`--provider` overrides it. `GROQ_TIMEOUT_SECONDS` defaults to 15 per HTTP I/O
operation. Eligible inference failures fall back; policy BLOCK/REVIEW never does.
Malformed requests and provider refusals fail visibly instead of switching models.
Both providers must pass the same Pydantic and deterministic artifact checks.

## Persistence and evidence

The runner accepts `--db`, `--session` and `--action`; default DB is `TETHER_DB`
or `runtime/tether.sqlite3`. Repeat a step key to replay its persisted result
without inference. Use a new action key to request another proposal. All fixture
prices/deployment statements are invented SYNTHETIC_DEMONSTRATION data.

Provider, actual model, timing and fallback reasons persist as inference timeline
events. Raw inference requests/responses are saved to unique `runtime/inference-*.json`
files and `runtime/inference.json` (latest). New benchmark files use unique
`runtime/benchmark-*.json` names and `runtime/benchmark-latest.json`; the original
Ollama benchmark remains at `runtime/benchmark.json`. Headers/API keys are not
logged. Runtime data is ignored by Git. Groq receives the inference prompts;
select `ollama` to keep inference local.

## Next integration checkpoint

Agree candidate shared schemas and connect the engine to FastAPI/Next.js. Display
one genuine action, validation/commit outcome, provider/fallback and persisted
report; verify restart recovery. Then implement approved goal evolution,
milestone transitions, specialists, review resolution and independent baseline
comparison. No complete-product or unmeasured performance claim is made.
