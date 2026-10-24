# Automatic workflow — 24 October 2026

Audited merged main `8158c58`; the remote HEAD matched the checkout. The GitHub
connector account cannot access this repository, so PR discussion and CI metadata
were not available. The user confirmed that the latest PR was already merged.

## Findings and changes

The previous product interface exposed the controlled demo step directly: users
had to create a session, execute each step, and confirm each milestone. Specialist
sessions forced Ollama even when Groq was configured. The new-project modal already
existed in source, but prefilled demo text obscured deliberate user input.

The modal now starts blank, accepts a name and objective, identifies the supported
cloud-comparison scope, offers agent mode, and starts the workflow server-side.
Projects and old artifacts remain intact. This is still a supplied-fixture cloud
comparison application, not a general arbitrary-goal executor.

A durable SQLite workflow claim owns sequential execution independently of the
browser. Committed artifacts advance milestones only with complete source coverage.
Review approval automatically schedules continuation. BLOCK, unresolved research,
incomplete evidence and provider failures stop visibly. Users can pause after the
in-flight step, or resume/retry without duplicating prior commits. On process
restart, interrupted work pauses explicitly instead of pretending it completed.
Existing step APIs remain for diagnostics and action-key replay. Report sections follow milestone order, and safe Markdown rendering displays actual tables instead of raw Markdown.

Research and Report now use the configured provider; Groq-primary/Ollama-backup,
Groq-only and offline modes remain explicit. Short Groq rate limits receive one
bounded retry honoring Retry-After (0–45 seconds), with waiting status persisted
in the timeline. Long/daily quota failures cannot be removed by retries. No policy
failure triggers fallback or automatic approval.

Comparison/recommendation always require substantive human review. Research prompts
require all authorized sources. Report prompts require all numerical declarations
as structured data and explicitly forbid unsupported deployment-simplicity rankings.
The synthetic sources describe approaches; they do not measure deployment complexity.

Groq rate-limit handling follows its [documented Retry-After header](https://console.groq.com/docs/rate-limits).

## Verification

- 129 automated Python tests pass. They cover the existing engine/provider/API
  boundaries plus full automatic milestone sequencing, review/continuation,
  partial-evidence regeneration, BLOCK/provider failures, concurrent duplicate
  claims, pause/resume, restart, and rate-limit parsing/retry bounds.
- Frontend TypeScript and production build pass.
- Browser-created **Groq sequential workflow verification** using custom name and
  objective. Genuine Groq Research and Report calls automatically committed M1/M2.
- A real Groq 429 initially reached local fallback; an invalid numerical declaration
  was BLOCKED without changing the report. After resuming, Groq generated a supported
  comparison. Its review approval automatically advanced into M4 generation.
- A recommendation initially overstated deployment simplicity. It was explicitly
  rejected and retained in history; the prompt was tightened to require the evidence
  limitation. The corrected Groq recommendation was reviewed and approved; the workflow completed all four milestones with four saved sections and no pending reviews. These are actual outcomes, not fabricated successful proposals.

The automated suite uses isolated databases and model doubles. Live observations
are smoke checks, not a statistical benchmark. Full matched multi-session baseline
measurement and comprehensive semantic-drift classification remain outside the
current verified implementation. Existing proposal evaluations remain available;
no improvement or perfect semantic correctness is claimed.
