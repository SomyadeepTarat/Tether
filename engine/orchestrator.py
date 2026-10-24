"""Single-agent first slice. A step key survives retries and process restarts."""
from engine.report_agent import plan_next_action

def run_step(store, client, project_id, session_id, references, action_id):
    session = store.db.execute("SELECT project FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session or session[0] != project_id:
        raise ValueError("Unknown session or project mismatch")
    prior = store.action_result(action_id)
    if prior:
        if prior.action.project_id != project_id or prior.action.session_id != session_id:
            raise ValueError("Action key belongs to another session")
        return prior.model_copy(update={"replayed": True})
    contract = store.current_contract(project_id)
    events = store.timeline(project_id)
    previous = next((e["body"] for e in reversed(events)
                     if e["kind"] in {"ACTION_BLOCK", "ACTION_REVIEW"}
                     and e["body"]["action"]["session_id"] == session_id), None)
    call_start = len(getattr(client, "calls", []))
    try:
        action = plan_next_action(client, contract, session_id, references, action_id,
                                  store.sections(project_id), previous)
    finally:
        calls = getattr(client, "calls", [])[call_start:]
        if calls:
            store.record_inference(project_id, session_id, action_id, calls)
    # Bind authority to application context instead of trusting model identity.
    if (action.action_id, action.project_id, action.session_id) != (action_id, project_id, session_id):
        raise ValueError("Model changed application-owned action identity")
    return store.commit_action(action, references)
