"""A handoff is untrusted evidence until identity, scope and sources pass checks."""
from engine.schemas import AgentHandoff, GoalContract, Reference, ValidationResult
from engine.validator import source_authorized


def validate_handoff(handoff: AgentHandoff, contract: GoalContract, session_id: str,
                     references: list[Reference]) -> ValidationResult:
    blocked, review = [], []
    if handoff.project_id != contract.project_id or handoff.session_id != session_id:
        blocked.append("Handoff project/session mismatch")
    if handoff.contract_version != contract.version:
        blocked.append("Handoff contract version is stale")
    milestone = next((m for m in contract.milestones if m.id == handoff.milestone_id), None)
    if not milestone or milestone.status != "ACTIVE":
        blocked.append("Handoff milestone is not active")
    if handoff.topic not in contract.approved_topics or (milestone and handoff.topic not in milestone.allowed_topics):
        blocked.append("Handoff topic is not authorized")
    if len({f.fact_id for f in handoff.findings}) != len(handoff.findings):
        blocked.append("Duplicate finding IDs")
    refs = {r.reference_id: r for r in references}
    for finding in handoff.findings:
        source = refs.get(finding.reference_id)
        if not source or source.provider != finding.provider:
            blocked.append("Unknown source or provider mismatch")
        elif not source_authorized(source, handoff.topic, contract):
            blocked.append("Handoff source topic is not authorized")
        elif finding.summary != source.summary:
            review.append("Finding is not an exact source quotation")
    if handoff.unresolved_questions:
        review.append("Research has unresolved questions")
    return ValidationResult(decision="BLOCK" if blocked else "REVIEW" if review else "ALLOW",
                            reasons=blocked + review)
