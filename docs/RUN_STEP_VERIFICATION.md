# Run next step — verification, 24 October 2026

## Causes observed

- Persisted user failures included Groq HTTP 429 rate limits, then an unavailable local Ollama fallback.
- Specialist sessions failed at the local Research Agent because Ollama could not be reached.
- Restarting with this workspace's Python environment exposed TLS certificate verification failure. Supplying only the certifi bundle excluded Windows-managed trusted roots. A verified connection succeeded using platform trust supplemented by certifi.

## Changes

- Groq HTTPS keeps platform trust, adds certifi roots, and respects explicit SSL_CERT_FILE configuration. Certificate verification and hostname verification remain enabled.
- TLS verification failures receive a distinct sanitized error category.
- Failure messages retain the hosted cause if the local backup also fails. Ollama missing-model errors no longer name Groq.
- Failed session reasons persist in the project response and timeline. The dashboard shows the reason and expands last-run details; its button reads Retry step.
- Retry preserves the pending action key and all existing validation rules.

## Verification

- 119 pytest cases passed. The suite covers provider routing, TLS trust and CA override, invalid output, failure recovery, duplicate replay, concurrency, validation, human review, goal versions and checkpoint recovery. Scripted cases use isolated databases/model doubles.
- Frontend TypeScript check and production build passed.
- Real Groq report call through the Next.js proxy committed the diagnostic project's cost section.
- The user's previously failed single-agent session S-3caf9c236218 recovered with its original action key A-867acc75cd32; ALLOW and one saved section. Replaying that key produced no additional inference or action.
- Browser click: Confirm complete on diagnostic cost milestone, then Run next step. Real Groq deployment output passed and committed, resulting in two diagnostic report sections.
- Screenshot: backend/data/run-step-verified.png.

## Limits

- Free-plan rate limits remain controlled by Groq. Repeated retries cannot remove a quota limit.
- Local specialist/fallback inference was not verified successfully on this machine: Ollama is unavailable. Install/start Ollama and the configured model before selecting local specialists.
- ALLOW, REVIEW and BLOCK remain distinct from provider/network failures. Model-generated prose can still require review; successful inference is not automatic policy approval.
- One Starlette/httpx deprecation warning remains in pytest. No tests failed in the final run.
