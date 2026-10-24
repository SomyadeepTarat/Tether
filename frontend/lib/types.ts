export type Milestone = {id:string;title:string;allowed_topics:string[];status?:string};
export type Contract = {project_id:string;version:number;objective:string;approved_topics:string[];constraints:{id:string;type:string;value:string|boolean;severity:string}[];milestones:Milestone[]};
export type Proposal = {contract_version:number;milestone_id:string;topic:string;section_id:string;content:string;reference_ids_used:string[];rationale:string};
export type Attempt = {provider?:string;model?:string;agent?:string;started_at?:string;attempt?:number;schema_valid?:boolean;elapsed_seconds?:number;error_kind?:string;http_status?:number;fallback_from?:string;fallback_reason?:string};
export type Inference = {session_id:string;action_id:string;attempts:Attempt[]};
export type EngineConfig = {provider:string;model:string;fallback_enabled:boolean;hosted_inputs:boolean;engine_available:boolean;review_approval_available:boolean;groq_key_configured:boolean};
export type Action = {id:string;session_id:string;body:Proposal;decision:'ALLOW'|'REVIEW'|'BLOCK';reason:string;created_at:string;inference?:Inference|null;resolution?:string|null;committed:boolean;review?:{decision:string;actor:string;reason:string}|null;action?:{declared_effects:Record<string,unknown>}};
export type Session = {id:string;status:string;created_at:string;mode:'single'|'specialists';pending_action?:string|null};
export type Handoff = {handoff:{handoff_id:string;source_agent:string;target_agent:string;milestone_id:string;topic:string;findings:{fact_id:string;provider:string;reference_id:string;summary:string}[]};validation:{decision:string;reasons:string[]};replayed:boolean;resolution?:string|null};
export type Change = {id:string;topic:string;status:string;base_version:number};
export type ProjectSummary = {id:string;name:string;created_at:string};
export type Project = ProjectSummary & {contract:Contract;sessions:Session[];actions:Action[];artifacts:Proposal[];changes:Change[];inference:Inference[];legacy_archive_available:boolean};
export type AuditEvent = {id:number;kind:string;message:string;created_at:string;body?:Inference|null};
export type EvaluationRun = {id:string;grader_version?:number;mode:'baseline'|'tether';case?:string;status:string;actual_models:string[];elapsed_seconds:number;error?:string;metrics?:{committed_actions:number;unauthorized_committed_actions:number;constraint_violations:number;source_fidelity:string;unauthorized_action_rate:number|null}};

export type Reference = {reference_id:string;provider:string;topic:string;summary:string;label:string};
