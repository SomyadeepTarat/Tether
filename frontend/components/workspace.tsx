import {ArrowRight,Check,CheckCheck,ChevronRight,FileCheck2,FileText,Flag,GitBranch,LoaderCircle,SearchCheck,ShieldCheck,Sparkles,Workflow} from 'lucide-react';
import type {Inference, Project} from '@/lib/types';

export function Badge({children,tone='muted'}:{children:React.ReactNode;tone?:string}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function stamp(value:string) {
  return value ? new Date(value).toLocaleString() : 'Historical event';
}

export function Empty({icon:Icon=FileText,title,children}:{icon?:typeof FileText;title:string;children:React.ReactNode}) {
  return <div className="empty"><span className="empty-icon"><Icon size={22}/></span><h3>{title}</h3><p>{children}</p></div>;
}

export function InferenceDetails({inference}:{inference?:Inference|null}) {
  if(!inference?.attempts.length) return <p className="inference-note">Provider details appear after the first run.</p>;
  return <div className="inference-details">{inference.attempts.map((a,i)=><div className="inference-attempt" key={i}>
    <div><Badge tone={a.error_kind?'amber':'green'}>{a.provider||'Unknown'}</Badge><strong>{a.model||'Unknown model'}</strong><small>{a.elapsed_seconds===undefined?'':`${a.elapsed_seconds.toFixed(2)}s`}</small></div>
    {a.agent&&<span className="attempt-agent">{a.agent.toLowerCase()} agent</span>}
    {a.fallback_from&&<p>Fallback from {a.fallback_from}: {a.fallback_reason?.replaceAll('_',' ')||'Provider unavailable'}</p>}
    {a.error_kind&&<p className="attempt-error">{a.error_kind.replaceAll('_',' ')}{a.http_status?` (HTTP ${a.http_status})`:''}</p>}
  </div>)}</div>;
}

export function WorkflowBoard({project,running,onReview}:{project:Project;running:boolean;onReview:()=>void}) {
  const last=project.actions[0];
  const failed=project.sessions[0]?.status==='FAILED';
  const pending=last?.decision==='REVIEW'&&!last.resolution;
  const status=running?'Working':failed?'Last run failed':last?.committed?'Committed':pending?'Needs review':last?.decision==='BLOCK'?'Blocked':'Ready';
  return <section className="panel workflow-panel">
    <div className="panel-heading"><h2><Workflow size={16}/>Your agent workflow</h2><Badge tone={running?'blue':failed?'red':'muted'}><span className={`dot ${running?'blue':failed?'red':''}`}/>{status}</Badge></div>
    <div className="workflow-canvas">
      <div className="canvas-label"><span className="dot blue"/> GOAL-ALIGNED EXECUTION <span>01 / WORKFLOW</span></div>
      <div className="flow-nodes">
        <div className={`flow-node ${running?'working':''}`}><span className="node-icon violet"><Sparkles size={21}/></span><small>01 · PROPOSE</small><h3>{project.sessions[0]?.mode==='specialists'?'Research + Report':'Report agent'}</h3><p>Turn evidence into a proposal</p><span className="node-status">{running?<LoaderCircle size={11} className="spin"/>:<span className={`dot ${failed?'red':''}`}/>}{running?'Generating':failed?'Retry available':'Ready to work'}</span></div>
        <span className="flow-connector"><ArrowRight size={14}/></span>
        <div className="flow-node"><span className="node-icon blue"><SearchCheck size={21}/></span><small>02 · VALIDATE</small><h3>Goal gateway</h3><p>Check scope, sources & effects</p><span className="node-status"><ShieldCheck size={12}/>Always enforced</span></div>
        <span className="flow-connector"><ArrowRight size={14}/></span>
        <div className="flow-node"><span className="node-icon peach"><FileCheck2 size={21}/></span><small>03 · COMMIT</small><h3>Saved report</h3><p>Keep only authorized work</p><span className="node-status"><FileText size={12}/>{project.artifacts.length} saved {project.artifacts.length===1?'section':'sections'}</span></div>
      </div>
      <div className="canvas-footer"><span><ShieldCheck size={13}/>Contract v{project.contract.version} protects every step</span><button onClick={onReview}>Inspect actions<ChevronRight size={13}/></button></div>
    </div>
  </section>;
}

export function MilestoneList({project,busy,running,onComplete}:{project:Project;busy:boolean;running:boolean;onComplete:(id:string)=>void}) {
  const completed=project.contract.milestones.filter(m=>m.status==='COMPLETED').length;
  return <section className="panel milestones" id="milestones"><div className="panel-heading"><h2><Flag size={16}/>Project milestones</h2><span className="subtle">{completed} of {project.contract.milestones.length} completed</span></div>
    <div className="milestone-list">{project.contract.milestones.map((m,i)=><div className={`milestone ${m.status?.toLowerCase()}`} key={m.id}>
      <span className="step-circle">{m.status==='COMPLETED'?<Check size={13}/>:String(i+1).padStart(2,'0')}</span>
      <div><h3>{m.title}</h3><span>{m.allowed_topics.join(' / ').toLowerCase()}</span></div>
      {m.status==='COMPLETED'?<CheckCheck size={16}/>:<Badge tone={m.status==='ACTIVE'?'blue':'muted'}>{m.status==='ACTIVE'?'In progress':'Pending'}</Badge>}
      {m.status==='ACTIVE'&&project.artifacts.some(a=>a.milestone_id===m.id)&&<button className="text-button" disabled={busy||running} onClick={()=>onComplete(m.id)}>Confirm complete<Check size={12}/></button>}
    </div>)}</div>
    <div className="panel-note"><GitBranch size={13}/>Progress changes. Your approved contract stays intact.</div>
  </section>;
}
