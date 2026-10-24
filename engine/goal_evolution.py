"""Append-only scope expansion. Approval comes from the authenticated application."""
from engine.schemas import GoalChange, GoalContract


def evolve_contract(current: GoalContract, change: GoalChange) -> GoalContract:
    if change.project_id != current.project_id or change.base_version != current.version:
        raise ValueError("Goal change targets a different project or stale version")
    if len(set(change.added_topics)) != len(change.added_topics):
        raise ValueError("Duplicate added topics")
    if set(change.added_topics) & set(current.approved_topics):
        raise ValueError("Added topics must be new")
    if len({m.id for m in change.added_milestones}) != len(change.added_milestones):
        raise ValueError("Duplicate added milestones")
    if {m.id for m in change.added_milestones} & {m.id for m in current.milestones}:
        raise ValueError("Existing milestones cannot be replaced")
    if any(m.status != "PENDING" for m in change.added_milestones):
        raise ValueError("New milestones must start pending")
    if set(change.added_topics) != {t for m in change.added_milestones for t in m.allowed_topics}:
        raise ValueError("New milestones must cover exactly the requested new topics")
    return GoalContract.model_validate({**current.model_dump(mode="json"),
        "version": current.version + 1,
        "approved_topics": [*current.approved_topics, *change.added_topics],
        "milestones": [m.model_dump(mode="json") for m in [*current.milestones, *change.added_milestones]]})
