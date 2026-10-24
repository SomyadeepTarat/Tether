"""Single-agent first slice. A step key survives retries and process restarts."""
from engine.report_agent import plan_next_action

def revision_feedback(store, session_id):
    row = store.db.execute("SELECT a.body,r.reason FROM action_reviews r JOIN actions a ON a.id=r.action_id WHERE json_extract(a.body,'$.session_id')=? AND r.decision='REJECTED' AND length(trim(r.reason))>0 ORDER BY a.rowid DESC LIMIT 1", (session_id,)).fetchone()
    if not row:
        return None
    import json
    return {'requested_changes':row[1], 'previous_draft':json.loads(row[0])['arguments']['content'][:2400]}


def run_step(store, client, project_id, session_id, references, action_id):
    session = store.db.execute("SELECT project FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session or session[0] != project_id:
        raise ValueError("Unknown session or project mismatch")
    prior = store.action_result(action_id)
    if prior:
        if prior.action.project_id != project_id or prior.action.session_id != session_id:
            raise ValueError("Action key belongs to another session")
        return prior.model_copy(update={"replayed": True})
    contract = store.effective_contract(project_id)
    events = store.timeline(project_id)
    previous = next((e["body"] for e in reversed(events)
                     if e["kind"] in {"ACTION_BLOCK", "ACTION_REVIEW"}
                     and e["body"]["action"]["session_id"] == session_id), None)
    call_start = len(getattr(client, "calls", []))
    try:
        feedback = revision_feedback(store, session_id)
        if contract.approved_topics == ["DRAFT"]:
            from engine.draft_agent import plan_draft
            action = plan_draft(client, contract, session_id, action_id, store.sections(project_id), feedback)
        else:
            action = plan_next_action(client, contract, session_id, references, action_id,
                                      store.sections(project_id), previous, task_note=__import__('json').dumps(feedback) if feedback else "")
    finally:
        calls = getattr(client, "calls", [])[call_start:]
        for call in calls:
            call.setdefault("agent", "REPORT")
        if calls:
            store.record_inference(project_id, session_id, action_id, calls)
    # Bind authority to application context instead of trusting model identity.
    if (action.action_id, action.project_id, action.session_id) != (action_id, project_id, session_id):
        raise ValueError("Model changed application-owned action identity")
    return store.commit_action(action, references)


def run_specialist_step(store, client, project_id, session_id, references, action_id):
    """Sequential research/gateway/report/gateway/commit; resumable at handoff."""
    from engine.research_agent import run_research_agent
    from engine.schemas import WorkflowResult
    from engine.report_agent import plan_next_action

    session = store.db.execute("SELECT project FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session or session[0] != project_id:
        raise ValueError("Unknown session or project mismatch")
    prior = store.action_result(action_id)
    if prior:
        if prior.action.project_id != project_id or prior.action.session_id != session_id:
            raise ValueError("Action key belongs to another session")
        return WorkflowResult(state="COMPLETED" if prior.committed else
                              "BLOCKED" if prior.validation.decision == "BLOCK" else "AWAITING_REVIEW",
                              step=prior.model_copy(update={"replayed": True}))
    contract = store.effective_contract(project_id)
    handoff_id = action_id + ":research"
    saved = store.handoff_result(handoff_id)
    phase = "RESEARCH"
    call_start = len(getattr(client, "calls", []))

    def flush_inference():
        nonlocal call_start
        calls = getattr(client, "calls", [])[call_start:]
        for call in calls:
            call.setdefault("agent", phase)
        if calls:
            store.record_inference(project_id, session_id, action_id, calls)
        call_start = len(getattr(client, "calls", []))

    try:
        handoff = saved.handoff if saved else run_research_agent(client, contract, session_id, references, handoff_id)
        flush_inference()
        if (handoff.handoff_id, handoff.project_id, handoff.session_id) != (handoff_id, project_id, session_id):
            raise ValueError("Research model changed application-owned identity")
        checked = store.save_handoff(handoff, references, action_id=action_id)
        if checked.validation.decision != "ALLOW":
            return WorkflowResult(state="BLOCKED" if checked.validation.decision == "BLOCK" else "AWAITING_REVIEW",
                                  handoff=checked)
        source_ids = {f.reference_id for f in handoff.findings}
        evidence = [r for r in references if r.reference_id in source_ids]
        phase = "REPORT"
        action = plan_next_action(client, contract, session_id, evidence, action_id,
                                  store.sections(project_id), handoff=handoff, task_note=__import__('json').dumps(revision_feedback(store, session_id)))
        flush_inference()
        if (action.action_id, action.project_id, action.session_id, action.milestone_id, action.topic) != (
                action_id, project_id, session_id, handoff.milestone_id, handoff.topic):
            raise ValueError("Report model changed application-owned handoff binding")
        # Only validated handoff sources can support this report action.
        result = store.commit_action(action, evidence)
        return WorkflowResult(state="COMPLETED" if result.committed else
                              "BLOCKED" if result.validation.decision == "BLOCK" else "AWAITING_REVIEW",
                              handoff=checked, step=result)
    finally:
        flush_inference()
