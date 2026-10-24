# Initial verification — 24 October 2026

Environment: Python 3.12.7; installed Ollama model qwen3:4b, Q4_K_M.
Dependency versions used are recorded in requirements-dev.lock.

## Observed local benchmark

Command: `PYTHONPATH=. .venv/bin/python scripts/benchmark.py`

Three short structured JSON probe requests produced three schema-valid outputs.
Wall times: 2.755, 0.509, 0.508 seconds. No probe failures or schema retries.
Ollama /api/ps reported 3,181,631,242 bytes model allocation/VRAM with a 4096-token
context. This is not measured peak system memory, and the first request is not
proven to be a cold start. Raw requests, responses, options, timings and model
metadata are stored in runtime/benchmark.json.

## Observed report proposals

Four authentic report proposals were made while refining instructions:

- A-001 BLOCK: missing section effects, synthetic label, numerical declarations
  and visible source citations; additional unsupported prose.
- A-002 BLOCK: mismatched section identifier and missing numerical declarations.
- A-003 BLOCK: a quotation typo failed exact evidence matching; no artifact write.
- A-004 ALLOW: exact fixture-backed cost quotations, citations and declared
  numerical evidence. One actual report artifact committed to SQLite.

These are development attempts with evolving prompts, not comparable evaluation
runs. They do not establish a model success rate or baseline improvement.
The successful attempt included prior persisted validation feedback. The gateway
was not relaxed to make model output pass. All failed proposals remain audited.
Raw inference records and report/database/timeline are in ignored runtime/.

## Verification

`.venv/bin/python -m pytest -q`: 20 passed.
Compile checks and git diff whitespace check passed.

A new Python process replayed A-004 without local network access or inference,
restored contract v1 and the cost artifact, and verified exactly one committed
action event. Transactional recovery/idempotency is also tested independently.
The live database has three blocked proposals, one committed proposal, and one
report section; no UI, full multi-session evaluation, approved v2 goal evolution,
or specialist handoff is claimed complete.

## Next step

Agree candidate schemas in shared/contracts and wire the engine into the
full-stack project/session/step/report APIs and Next.js Command Center. The first
cross-stack acceptance check is displaying the persisted genuine action and its
report, then restarting the backend and showing the same state without a duplicate
commit. Continue milestone progression, goal-change authorization, specialists,
and independent baseline grading after that checkpoint.

## Provider change verification

The user subsequently approved Groq primary/Ollama backup (see TEAMMATE_UPDATE.md).
The original benchmark above remains an Ollama-only historical observation.
No Groq key is set: remote API calls/latency remain unverified. Mock HTTP tests
exercise the strict request shape, success, authentication/rate-limit/server/
network/schema failures, refusal, secret exclusion and routing boundaries.

A genuine missing-key fallback probe passed in 2.713 seconds. A genuine fallback
report proposal passed validation and committed in runtime/groq-fallback.sqlite3;
the Ollama report call took 13.355 seconds. Its persisted INFERENCE_COMPLETED
event identifies both the missing Groq credentials and the actual Ollama model.
Fresh-process replay required no inference and did not duplicate the commit.
Current test suite: 40 passed. These observations are not a Groq speed benchmark
or a baseline-versus-Tether evaluation.
