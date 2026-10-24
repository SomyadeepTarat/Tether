"""Conservative checks. Semantic uncertainty is REVIEW, never an implicit approval."""
import re
from engine.schemas import AgentAction, GoalContract, Reference, ValidationResult

NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")
SCOPE = {"SECURITY": r"\b(security|compliance|soc\s*2|hipaa|enterprise governance)\b",
         "SERVERLESS": r"\b(serverless|lambda|cloud functions|azure functions)\b"}

def source_authorized(reference: Reference, topic, contract: GoalContract) -> bool:
    if reference.topic not in contract.approved_topics:
        return False
    if topic in {"COMPARISON", "RECOMMENDATION"}:
        return reference.topic in {"COST", "DEPLOYMENT", "SERVERLESS"}
    return reference.topic == topic


def validate_action(action: AgentAction, contract: GoalContract, session_id: str,
                    references: list[Reference], existing_sections: set[str] | None = None) -> ValidationResult:
    blocked, review = [], []
    refs = {r.reference_id: r for r in references}
    if action.project_id != contract.project_id or action.session_id != session_id:
        blocked.append("Project/session identity mismatch")
    if action.contract_version != contract.version:
        blocked.append("Stale or unapproved contract version")
    milestone = next((m for m in contract.milestones if m.id == action.milestone_id), None)
    if milestone is None or milestone.status != "ACTIVE":
        blocked.append("Milestone is not active")
    if action.topic not in contract.approved_topics or (milestone and action.topic not in milestone.allowed_topics):
        blocked.append("Topic is not authorized for this milestone")
    effects = action.declared_effects
    if set(effects.topics_introduced) != {action.topic}:
        blocked.append("Declared topics do not match action topic")
    existing = existing_sections or set()
    section = action.arguments.section_id
    created, modified = ([section], []) if section not in existing else ([], [section])
    if effects.sections_created != created or effects.sections_modified != modified:
        blocked.append("Declared section effects do not match actual write")
    for rid in effects.reference_ids_used:
        if rid not in refs:
            blocked.append(f"Unknown source: {rid}")
        elif not source_authorized(refs[rid], action.topic, contract):
            blocked.append(f"Source topic mismatch: {rid}")
    if action.topic == "COST" and not effects.numerical_claims:
        blocked.append("Cost section must include supported numerical evidence")
    content = action.arguments.content
    if "SYNTHETIC_DEMONSTRATION" not in content:
        blocked.append("Artifact must label synthetic demonstration data")
    for topic, pattern in SCOPE.items():
        if re.search(pattern, content, re.I) and topic not in contract.approved_topics:
            blocked.append(f"Content introduces unauthorized topic: {topic}")
    if re.search(r"https?://", content):
        blocked.append("External source URL in fixture-only artifact")
    declared_numbers = set()
    for claim in effects.numerical_claims:
        source = refs.get(claim.reference_id)
        if (not source or claim.reference_id not in effects.reference_ids_used
            or claim.value not in source.numerical_values or claim.quote not in source.summary
            or claim.value not in claim.quote or claim.quote not in content):
            blocked.append("Unsupported numerical claim or mismatched evidence quote")
        declared_numbers.update(NUMBER.findall(claim.value))
    # Strip cited source identifiers before inspecting numerical content.
    clean = content
    for rid in refs:
        clean = clean.replace(rid, "")
    if set(NUMBER.findall(clean)) - declared_numbers:
        blocked.append("Undeclared numerical content")
    if not all(rid in content for rid in effects.reference_ids_used):
        review.append("Content does not visibly cite declared sources")
    # Arbitrary paraphrases require human review in this first slice. Exact fixture
    # quotations give a small, auditable automatic path without an LLM self-grader.
    residual = content.replace("SYNTHETIC_DEMONSTRATION", "")
    for rid in effects.reference_ids_used:
        if rid in refs:
            residual = residual.replace(refs[rid].summary, "").replace(rid, "")
    if re.sub(r"[\W_]", "", residual):
        review.append("Free-form claims require semantic review")
    return ValidationResult(decision="BLOCK" if blocked else "REVIEW" if review else "ALLOW",
                            reasons=blocked + review)
