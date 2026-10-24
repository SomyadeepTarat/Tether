"""Shared v1 wire contracts. Unknown fields are rejected, never silently ignored."""
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class Topic(StrEnum):
    DRAFT = "DRAFT"
    COST = "COST"
    DEPLOYMENT = "DEPLOYMENT"
    COMPARISON = "COMPARISON"
    RECOMMENDATION = "RECOMMENDATION"
    SERVERLESS = "SERVERLESS"
    SECURITY = "SECURITY"

class Constraint(Model):
    id: str
    type: Literal["SOURCE_RESTRICTION", "NO_UNAUTHORIZED_SCOPE"]
    value: str | bool
    severity: Literal["HARD"] = "HARD"

class Milestone(Model):
    id: str
    title: str
    allowed_topics: list[Topic] = Field(min_length=1)
    status: Literal["ACTIVE", "PENDING", "COMPLETED"] = "PENDING"

class GoalContract(Model):
    project_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    objective: str = Field(min_length=1)
    constraints: list[Constraint]
    milestones: list[Milestone] = Field(min_length=1)
    approved_topics: list[Topic] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.milestones, self.constraints):
            if len({v.id for v in values}) != len(values):
                raise ValueError("Duplicate identifiers")
        if any(not set(m.allowed_topics) <= set(self.approved_topics) for m in self.milestones):
            raise ValueError("Milestone topic is not approved")
        return self

class Reference(Model):
    reference_id: str
    provider: Literal["AWS", "AZURE", "GCP"]
    topic: Topic
    summary: str
    numerical_values: list[str] = Field(default_factory=list)
    label: Literal["SYNTHETIC_DEMONSTRATION"] = "SYNTHETIC_DEMONSTRATION"

class NumericalClaim(Model):
    value: str
    reference_id: str
    quote: str

class DeclaredEffects(Model):
    sections_created: list[str] = Field(default_factory=list)
    sections_modified: list[str] = Field(default_factory=list)
    topics_introduced: list[Topic]
    reference_ids_used: list[str] = Field(default_factory=list)
    numerical_claims: list[NumericalClaim] = Field(default_factory=list)

class Section(Model):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    content: str = Field(min_length=1, max_length=16000)

class AgentAction(Model):
    action_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    agent: Literal["REPORT"] = "REPORT"
    session_id: str = Field(min_length=1)
    contract_version: int = Field(ge=1)
    action_type: Literal["WRITE_SECTION"] = "WRITE_SECTION"
    milestone_id: str
    topic: Topic
    declared_effects: DeclaredEffects
    arguments: Section
    rationale: str

class Finding(Model):
    fact_id: str
    provider: Literal["AWS", "AZURE", "GCP"]
    reference_id: str
    summary: str

class AgentHandoff(Model):
    handoff_id: str
    project_id: str
    session_id: str
    contract_version: int
    source_agent: Literal["RESEARCH"] = "RESEARCH"
    target_agent: Literal["REPORT"] = "REPORT"
    milestone_id: str
    topic: Topic
    findings: list[Finding] = Field(min_length=1)
    unresolved_questions: list[str] = Field(default_factory=list)
    completed_work: list[str] = Field(default_factory=list)
    next_action: str

class ValidationResult(Model):
    decision: Literal["ALLOW", "REVIEW", "BLOCK"]
    reasons: list[str]

class StepResult(Model):
    action: AgentAction
    validation: ValidationResult
    committed: bool
    replayed: bool = False

class GoalChange(Model):
    change_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    base_version: int = Field(ge=1)
    added_topics: list[Topic] = Field(min_length=1)
    added_milestones: list[Milestone] = Field(min_length=1)
    rationale: str = Field(min_length=1)

class HandoffResult(Model):
    handoff: AgentHandoff
    validation: ValidationResult
    replayed: bool = False

class WorkflowResult(Model):
    state: Literal["BLOCKED", "AWAITING_REVIEW", "COMPLETED"]
    handoff: HandoffResult | None = None
    step: StepResult | None = None
