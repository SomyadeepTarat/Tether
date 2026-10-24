# Workflow merge resolution — 24 October 2026

Resolved all eight content conflicts in .env.example, README.md,
backend/inference.py, engine/llm_client.py, frontend/app/globals.css,
frontend/app/page.tsx, frontend/lib/types.ts and tests/test_inference.py.

The incoming workspace redesign, reusable components, responsive navigation,
keyboard shortcuts, project search and stale-response protection are retained.
The existing source-evidence view, declared effects, explicit human REVIEW
approval/rejection, specialist rejection/resumption, restore/fresh-demo controls
and real evaluation results are integrated into that design. Review cannot
turn a deterministic BLOCK into an approval.

Workflow status follows the latest session rather than an old project's last
committed action. The board shows actual research, handoff check, report, action
check, commit and checkpoint states. Pending research routes to its findings;
report reviews route to the action inspector. Milestone progression, immutable
goal versions and historical provider attribution remain intact.

Groq uses the incoming application User-Agent Tether/0.2 together with the
existing verified certifi TLS context. Backend credential detection and sanitized
failure messages are retained. Configuration precedence is process environment,
then backend/.env, then root .env. The earlier duplicate root loader was removed
from backend startup so it cannot preempt backend/.env. The engine CLI retains
root .env loading. Both loaders preserve literal values and support UTF-8 BOM.
No credentials are staged or printed.

Verification: 102 Python tests pass, including a full HTTP workflow test covering
initial commit, drift rejection, approved contract v2, restart/replay, explicit
review approval, all five milestones and completed-project enforcement. These
integration tests use scripted model doubles; they do not claim model quality.
Frontend TypeScript and production build pass. Conflict-marker and whitespace
checks are clean. Incoming presentation artifacts are preserved unchanged.
