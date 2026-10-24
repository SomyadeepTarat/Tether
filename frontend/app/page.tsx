'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {Activity,ArrowRight,ArrowUpRight,Bot,Check,ChevronDown,ChevronRight,CircleHelp,Clock3,FileText,Flag,GitBranch,History,House,Layers3,LoaderCircle,PanelLeftClose,Plus,Radio,RefreshCw,Search,ShieldCheck,ShieldX,Sparkles,Workflow,X} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Badge,Empty,InferenceDetails,MilestoneList,stamp,WorkflowBoard} from '@/components/workspace';
import {api} from '@/lib/api';
import {Evaluation} from '@/components/evaluation';
import type {Action,AuditEvent,Contract,Project,ProjectSummary,EngineConfig,Handoff,EvaluationRun,Reference} from '@/lib/types';

const tabs=['Command center','Drift inspector','History & evaluation'] as const;
type Tab=typeof tabs[number];
const names:Record<Tab,string>={'Command center':'Overview','Drift inspector':'Action review','History & evaluation':'History & evaluation'};

export default function Home(){
  const [sourceReferences,setSourceReferences]=useState<Reference[]>([]);
  const [evaluations,setEvaluations]=useState<EvaluationRun[]>([]);
  const [reviewReason,setReviewReason]=useState('');
  const [config,setConfig]=useState<EngineConfig|null>(null);
  const [mode,setMode]=useState<'single'|'specialists'>('single');
  const [handoffs,setHandoffs]=useState<Handoff[]>([]);
  const [projects,setProjects]=useState<ProjectSummary[]>([]);
  const [project,setProject]=useState<Project|null>(null);
  const [tab,setTab]=useState<Tab>('Command center');
  const [events,setEvents]=useState<AuditEvent[]>([]);
  const [contracts,setContracts]=useState<Contract[]>([]);
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [createOpen,setCreateOpen]=useState(false),[selected,setSelected]=useState<string|null>(null);
  const [search,setSearch]=useState(''),[mobileNav,setMobileNav]=useState(false);
  const [name,setName]=useState('Startup cloud comparison');
  const [objective,setObjective]=useState('Compare AWS, Azure, and Google Cloud for a startup. Prioritize cost and deployment simplicity.');
  const dialogRef=useRef<HTMLDialogElement>(null);
  const searchRef=useRef<HTMLInputElement>(null);
  const requestId=useRef(0);

  const refresh=useCallback(async(id?:string)=>{
    const request=++requestId.current;
    const [list,health]=await Promise.all([api<ProjectSummary[]>('/projects'),api<EngineConfig>('/health')]);
    if(request!==requestId.current)return;
    setProjects(list);setConfig(health);
    const target=id||list[0]?.id;
    if(target){
      const [p,e,c,metrics,refs]=await Promise.all([api<Project>(`/projects/${target}`),api<AuditEvent[]>(`/projects/${target}/timeline`),api<Contract[]>(`/projects/${target}/contracts`),api<{runs:EvaluationRun[]}>(`/projects/${target}/metrics`),api<Reference[]>(`/projects/${target}/references`)]);
      if(request!==requestId.current)return;
      setProject(p);setEvents(e);setContracts(c);setEvaluations(metrics.runs);setSourceReferences(refs);
      if(p.sessions[0]){
        const h=await api<{handoffs:Handoff[]}>(`/sessions/${p.sessions[0].id}/handoffs`);
        if(request===requestId.current)setHandoffs(h.handoffs);
      }else setHandoffs([]);
    }
  },[]);
  useEffect(()=>{refresh().catch(e=>setError(e.message)).finally(()=>setLoading(false));},[refresh]);
  useEffect(()=>{
    if(!project?.sessions.some(s=>['PLANNING','VALIDATING','HANDOFF'].includes(s.status)))return;
    const timer=setInterval(()=>void refresh(project.id).catch(()=>{}),2500);
    return()=>clearInterval(timer);
  },[project,refresh]);
  useEffect(()=>{
    if(createOpen)dialogRef.current?.showModal();else dialogRef.current?.close();
  },[createOpen]);
  useEffect(()=>{
    function shortcut(event:KeyboardEvent){
      const editing=event.target instanceof HTMLElement&&!!event.target.closest('input,textarea,select,[contenteditable="true"]');
      if(!editing&&event.key==='/'){event.preventDefault();searchRef.current?.focus();}
      if(!editing&&event.key.toLowerCase()==='n'&&!event.metaKey&&!event.ctrlKey&&!event.altKey){event.preventDefault();setCreateOpen(true);}
      if(event.key==='Escape')setMobileNav(false);
    }
    window.addEventListener('keydown',shortcut);
    return()=>window.removeEventListener('keydown',shortcut);
  },[]);

  async function run(work:()=>Promise<unknown>){
    setBusy(true);setError('');
    try{await work();await refresh(project?.id);}catch(e){setError(e instanceof Error?e.message:'Something went wrong');if(project)await refresh(project.id).catch(()=>{});}finally{setBusy(false);}
  }
  async function create(){
    setBusy(true);setError('');
    try{const p=await api<{id:string}>('/projects',{name,objective});await refresh(p.id);setCreateOpen(false);}catch(e){setError(e instanceof Error?e.message:'Project creation failed');}finally{setBusy(false);}
  }
  async function freshDemo(){
    if(!project)return;
    setBusy(true);setError('');
    try{const p=await api<{id:string}>('/demo/reset',{project_id:project.id});await refresh(p.id);setSelected(null);setReviewReason('');}catch(e){setError(e instanceof Error?e.message:'Demo reset failed');}finally{setBusy(false);}
  }
  function resolveReview(action:Action,decision:'APPROVE'|'REJECT'){
    return run(async()=>{await api(`/actions/${action.id}/decision`,{decision,reason:reviewReason});setReviewReason('');});
  }
  function navigate(next:Tab){setTab(next);setMobileNav(false);}
  function scrollTo(id:string){setTab('Command center');setMobileNav(false);requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({behavior:'smooth',block:'start'}));}
  async function chooseProject(id:string){setBusy(true);setError('');try{await refresh(id);setMobileNav(false);setSelected(null);setReviewReason('');}catch(e){setError(e instanceof Error?e.message:'Could not open project');}finally{setBusy(false);}}

  const latest=project?.sessions[0];
  const lastInference=project?.inference?.[project.inference.length-1];
  const lastAttempt=lastInference?.attempts[lastInference.attempts.length-1];
  const researchNeedsReview=handoffs.some(h=>h.validation.decision==='REVIEW'&&!h.resolution);
  const pending=(project?.actions.filter(a=>a.decision==='REVIEW'&&!a.resolution).length||0)+handoffs.filter(h=>h.validation.decision==='REVIEW'&&!h.resolution).length;
  const running=!!project?.sessions.some(s=>['PLANNING','VALIDATING','HANDOFF'].includes(s.status));
  const completed=project?.contract.milestones.filter(m=>m.status==='COMPLETED').length||0;
  const inspected=project?.actions.find(a=>a.id===selected)||project?.actions[0];
  const filteredProjects=projects.filter(p=>p.name.toLowerCase().includes(search.toLowerCase()));
  const filteredActions=project?.actions.filter(a=>`${a.body.topic} ${a.body.content} ${a.reason}`.toLowerCase().includes(search.toLowerCase()))||[];
  const sessionState=running?'Working':latest?.status.replaceAll('_',' ').toLowerCase()||'Not started';
  const approved=project?.actions.filter(a=>a.committed).length||0;
  const blocked=project?.actions.filter(a=>a.decision==='BLOCK').length||0;

  return <div className={`shell ${mobileNav?'nav-open':''}`}>
    {mobileNav&&<button className="nav-scrim" aria-label="Close navigation" onClick={()=>setMobileNav(false)}/>}
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-symbol"><Workflow size={22}/></span>Tether</a>
      <div className="workspace"><span className="workspace-icon"><Layers3 size={17}/></span><div>Tether workspace<small>Personal workspace</small></div><Badge>LOCAL</Badge></div>
      <Button className="new-project" onClick={()=>setCreateOpen(true)}><Plus size={15}/>New project<span>N</span></Button>
      <div className="nav-label">Main</div>
      <nav aria-label="Main navigation">{tabs.map((t,i)=>{const Icon=[House,ShieldCheck,History][i];return <button key={t} onClick={()=>navigate(t)} className={`nav-item ${tab===t?'active':''}`} aria-current={tab===t?'page':undefined}><Icon size={17}/><span>{names[t]}</span>{t==='Drift inspector'&&pending>0&&<span className="nav-count">{pending}</span>}</button>;})}
        <button className="nav-item" disabled={!project} onClick={()=>scrollTo('report')}><FileText size={17}/><span>Report artifacts</span></button>
        <button className="nav-item" disabled={!project} onClick={()=>scrollTo('milestones')}><Flag size={17}/><span>Milestones</span></button>
      </nav>
      <div className="nav-label projects-label">Projects<button aria-label="Create project" onClick={()=>setCreateOpen(true)}><Plus size={14}/></button></div>
      <div className="project-list">{filteredProjects.map((p,i)=><button disabled={busy} className={`project-link ${p.id===project?.id?'chosen':''}`} key={p.id} onClick={()=>void chooseProject(p.id)}><span className={`project-dot color-${i%3}`}/><span>{p.name}</span>{p.id===project?.id&&<span className="project-active"/>}</button>)}{!filteredProjects.length&&<p className="sidebar-hint">{search?'No matching projects.':'Your next idea starts here.'}</p>}</div>
      <div className="sidebar-bottom"><div className="local-card"><span className="local-mark"><ShieldCheck size={18}/></span><strong>A goal worth keeping.</strong><p>Your progress stays saved.<br/>Pick up right where you left off.</p><button onClick={()=>navigate('History & evaluation')}>Explore your history<ArrowUpRight size={13}/></button></div>
      <details className="profile-menu"><summary><span className="avatar">TE</span><div>Tether workspace<small>Local operator</small></div><ChevronDown size={14}/></summary><div className="profile-popover"><strong>Personal environment</strong><p>Projects are stored locally in SQLite. Your inference provider is configured on the backend.</p><Badge tone="green">{config?.provider||'Loading provider'}</Badge></div></details></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={()=>setMobileNav(true)}><PanelLeftClose size={18}/></button><span className="crumb-workspace">Workspace</span><ChevronRight size={13}/><span>{names[tab]}</span></div>
        <div className="topbar-right"><label className="search"><Search size={15}/><input ref={searchRef} aria-label="Search projects and actions" placeholder="Search workspace..." value={search} onChange={e=>setSearch(e.target.value)}/><kbd>/</kbd></label><details className="help-menu"><summary aria-label="Workspace help"><CircleHelp size={18}/></summary><div className="help-popover"><strong>A little help getting started</strong><p>Create a project, start a session, then run a step. Review the proposal and confirm milestones as you go.</p><p>Groq needs a backend API key. Local sessions need Ollama running with the configured model.</p></div></details><span className="topbar-divider"/><span className="avatar">TE</span></div>
      </header>
      <main>
        <div className="page-heading"><div><div className="eyebrow"><span className="dot"/>YOUR WORKSPACE, CONNECTED</div><h1>{tab==='Command center'?'Good work starts with a clear goal.':names[tab]}</h1><p>{tab==='Command center'?'A little direction for your agents. A lot more confidence in what comes next.':tab==='Drift inspector'?'Every proposal, every check. See what moves your goal forward.':'The decisions and small steps behind the bigger picture.'}</p></div><div className="heading-actions">{project&&<Button variant="outline" disabled={busy||running} onClick={()=>void freshDemo()} title="Creates a fresh project and preserves existing history"><Plus size={14}/>Fresh demo</Button>}<button className="icon-button refresh-button" title="Refresh workspace" aria-label="Refresh workspace" disabled={busy} onClick={()=>void run(()=>refresh(project?.id))}><RefreshCw size={16} className={busy?'spin':''}/></button><Button onClick={()=>setCreateOpen(true)}><Plus size={15}/>New project</Button></div></div>

        {error&&<div className="error" role="alert"><ShieldX size={17}/><span>{error}</span><button aria-label="Dismiss error" onClick={()=>setError('')}><X size={15}/></button></div>}
        {loading?<div className="loading-state"><LoaderCircle className="spin" size={24}/><p>Opening your workspace...</p></div>:!project?<section className="welcome panel"><div className="welcome-illustration"><span className="float-chip"><ShieldCheck size={15}/>Goal protected</span><span className="bot-face"><Bot size={67} strokeWidth={1}/></span><span className="float-chip second"><Check size={13}/>Ready when you are</span></div><Badge tone="blue">A FRESH START</Badge><h2>Your idea. Your agents.<br/>One clear direction.</h2><p>Give your agents a goal they can return to. Tether keeps every proposal, decision, and session connected.</p><Button onClick={()=>setCreateOpen(true)}><Plus size={16}/>Create your first project<ArrowRight size={15}/></Button><div className="welcome-features"><span><ShieldCheck size={15}/>Controlled execution</span><span><GitBranch size={15}/>Versioned goals</span><span><History size={15}/>Saved progress</span></div></section>:<>

        <div className="project-toolbar"><div><span className="project-dot color-0"/><select className="project-switcher" aria-label="Active project" disabled={busy} value={project.id} onChange={e=>void chooseProject(e.target.value)}>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><Badge tone="green">Contract v{project.contract.version}</Badge></div><span><span className="dot"/>{config?.provider==='ollama'?'Local inference':config?.provider==='groq-only'?'Groq only':'Groq + Ollama backup'}</span></div>

        {tab==='Command center'&&<>
          <section className="stats" aria-label="Project overview">
            <div className="stat-card"><span className="stat-label"><Flag size={14}/>Milestones</span><strong>{completed}<small>/{project.contract.milestones.length}</small></strong><div className="stat-bottom"><span>{project.contract.milestones.length-completed} remaining</span><div className="mini-bars green">{Array.from({length:12},(_,i)=><i key={i} className={i<Math.round(completed/project.contract.milestones.length*12)?'filled':''}/>)}</div></div></div>
            <div className="stat-card"><span className="stat-label"><FileText size={14}/>Committed sections</span><strong>{project.artifacts.length}</strong><div className="stat-bottom"><span>Validated & saved</span><span className="stat-symbol blue"><FileText size={24}/></span></div></div>
            <div className="stat-card"><span className="stat-label"><ShieldCheck size={14}/>Actions checked</span><strong>{project.actions.length}</strong><div className="stat-bottom"><span>{approved} allowed · {blocked} blocked</span><span className="stat-symbol violet"><ShieldCheck size={24}/></span></div></div>
            <div className="stat-card"><span className="stat-label"><Clock3 size={14}/>Needs attention</span><strong>{pending}</strong><div className="stat-bottom"><span>{pending?'Waiting for your review':'No pending reviews'}</span><span className="stat-symbol peach"><Clock3 size={24}/></span></div></div>
          </section>

          <div className="overview-grid"><WorkflowBoard project={project} running={running} handoffs={handoffs} onReview={()=>navigate('Drift inspector')} onResearch={()=>scrollTo('handoffs')}/><section className="panel goal-card"><div className="panel-heading"><h2><Flag size={16}/>The bigger picture</h2><Badge>v{project.contract.version}</Badge></div><div className="goal-body"><span className="eyebrow">YOUR APPROVED GOAL</span><h3>{project.contract.objective}</h3><div className="topic-chips">{project.contract.approved_topics.map(t=><span key={t}>{t.toLowerCase()}</span>)}</div><div className="goal-rule"><ShieldCheck size={14}/>Supplied references only</div><div className="goal-rule"><GitBranch size={14}/>Scope changes need your approval</div><button className="text-button goal-change" disabled={busy||project.contract.approved_topics.includes('SERVERLESS')||project.changes.some(c=>c.status==='PENDING')} onClick={()=>void run(()=>api(`/projects/${project.id}/changes`,{topic:'SERVERLESS'}))}>{project.contract.approved_topics.includes('SERVERLESS')?<><Check size={13}/>Serverless scope approved</>:<>Add serverless comparison<ArrowUpRight size={14}/></>}</button></div></section></div>

          {project.changes.filter(c=>c.status==='PENDING').map(c=><div className="approval-banner" key={c.id}><span className="node-icon peach"><GitBranch size={20}/></span><div><strong>A new direction, with your approval.</strong><p>Add serverless comparison and milestone M5 to contract v{c.base_version+1}.</p></div><Button variant="outline" disabled={busy} onClick={()=>void run(()=>api(`/changes/${c.id}/decision`,{decision:'REJECT'}))}>Reject</Button><Button disabled={busy||!!pending||running} onClick={()=>void run(()=>api(`/changes/${c.id}/decision`,{decision:'APPROVE'}))}>Approve change<Check size={14}/></Button></div>)}

          <section className="recent-section"><div className="section-heading"><h2>Recent activity<span className="count-label">{events.length}</span></h2><button className="text-button" onClick={()=>navigate('History & evaluation')}>View all activity<ArrowUpRight size={14}/></button></div><div className="activity-cards">{events.slice(0,3).map((e,i)=><article className="activity-card" key={e.id}><div><span className={`activity-event-icon ${['violet','peach','blue'][i]}`}>{e.kind.includes('CONTRACT')||e.kind.includes('GOAL')?<GitBranch size={16}/>:e.kind.includes('FAIL')?<ShieldX size={16}/>:<Workflow size={16}/>}</span><Badge tone={e.kind.includes('FAIL')?'red':e.kind.includes('BLOCK')?'amber':'muted'}>{e.kind.replaceAll('_',' ').toLowerCase()}</Badge></div><p>{e.message}</p><small><Clock3 size={11}/>{stamp(e.created_at)}</small></article>)}</div></section>

          <div className="work-grid"><MilestoneList project={project} busy={busy} running={running} onComplete={id=>void run(()=>api(`/projects/${project.id}/milestones/${id}/complete`,{}))}/><section className="panel agent-panel"><div className="panel-heading"><h2><Bot size={17}/>Your agents</h2><Badge tone={running?'blue':latest?.status==='FAILED'?'red':'muted'}>{sessionState}</Badge></div><div className="agent-row"><span className="agent-icon"><Bot size={25} strokeWidth={1.4}/></span><div><strong>{latest?.mode==='specialists'?'Research + Report':'Report agent'}</strong><p>{lastAttempt?`${lastAttempt.provider} / ${lastAttempt.model}`:`${config?.provider||'Loading'} / ${config?.model||''}`}</p></div><span className="agent-mode">{latest?.mode==='specialists'?'2 AGENTS':'1 AGENT'}</span></div><div className="activity-box"><span className={`dot ${running?'blue':''}`}/><div><strong>{running?'Your agent is working':pending?'A proposal needs your attention':latest?.status==='FAILED'?'Your last run needs a retry':'Ready for the next small step'}</strong><p>{pending?'Open action review to inspect the proposal and its validation.':latest?.status==='FAILED'?'Check provider availability below. Retrying will use the same saved action key.':'Every proposal passes through the goal gateway before it can be saved.'}</p></div>{pending>0&&<button aria-label={researchNeedsReview?'Open research review':'Open action review'} onClick={()=>researchNeedsReview?scrollTo('handoffs'):navigate('Drift inspector')}><ArrowUpRight size={16}/></button>}</div>{config?.hosted_inputs&&latest?.mode!=='specialists'&&<div className={`provider-setup ${config.groq_key_configured?'configured':''}`}><ShieldCheck size={14}/><div><strong>{config.groq_key_configured?'Groq key detected by backend':'Groq key is not configured'}</strong><p>{config.groq_key_configured?'Authentication is checked when you run a step.':'Add GROQ_API_KEY to the repository .env file, restart FastAPI, then refresh this workspace.'}</p></div></div>}<InferenceDetails inference={lastInference}/><label className="mode-select">New session mode<select disabled={busy||running} value={mode} onChange={e=>setMode(e.target.value as 'single'|'specialists')}><option value="single">Single report agent · configured provider</option><option value="specialists">Research + Report · local Ollama</option></select></label><div className="session-controls"><Button variant="outline" disabled={busy||running||!!pending} onClick={()=>void run(()=>api(`/projects/${project.id}/sessions`,{mode}))}><Plus size={14}/>{latest?'New session':'Start session'}</Button><Button variant="outline" disabled={busy||running} onClick={()=>void run(()=>api(`/projects/${project.id}/recover`,{}))}><History size={14}/>Restore saved state</Button><Button disabled={busy||running||!!pending||!latest||completed===project.contract.milestones.length} onClick={()=>void run(()=>api(`/sessions/${latest!.id}/step`,{}))}>{busy||running?<LoaderCircle size={14} className="spin"/>:<Sparkles size={14}/>}Run next step<ArrowRight size={14}/></Button></div><p className="engine-note">{config?.engine_available?'Exact source quotations may commit automatically. Review free-form claims and their evidence before approving.':'The AI engine is not available yet.'}</p></section></div>

          {handoffs.length>0&&<section className="panel handoff-panel" id="handoffs"><div className="panel-heading"><h2><Workflow size={16}/>Research → report handoffs</h2><Badge>LOCAL SPECIALISTS</Badge></div>{handoffs.map(h=><div className="detail-content" key={h.handoff.handoff_id}><div className="detail-meta"><span>{h.handoff.source_agent} → {h.handoff.target_agent}</span><span>{h.handoff.milestone_id} / {h.handoff.topic}</span><Badge tone={h.validation.decision==='ALLOW'?'green':h.validation.decision==='BLOCK'?'red':'amber'}>{h.validation.decision}</Badge>{h.replayed&&<Badge>Restored</Badge>}</div>{h.handoff.findings.map(f=><p key={f.fact_id}><strong>{f.provider}</strong>: {f.summary}<br/><small>{f.reference_id}</small></p>)}{h.validation.reasons.length>0&&<p>{h.validation.reasons.join('; ')}</p>}{h.resolution&&<Badge>{h.resolution}</Badge>}{!h.resolution&&h.validation.decision!=='ALLOW'&&latest?.pending_action===h.handoff.handoff_id.replace(/:research$/,'')&&<Button variant="danger" disabled={busy||running} onClick={()=>void run(()=>api(`/sessions/${latest.id}/pending/decision`,{decision:'REJECT'}))}>Reject research proposal</Button>}</div>)}</section>}

          <section className="panel report-panel" id="report"><div className="panel-heading"><h2><FileText size={16}/>Report artifacts</h2><Badge tone="green"><span className="dot"/>Committed only</Badge></div>{project.artifacts.length?<div className="report-content">{project.artifacts.map(a=><article key={a.section_id}><span className="eyebrow">{a.topic} / {a.milestone_id}</span><h3>{a.section_id.replaceAll('_',' ')}</h3><p>{a.content}</p><div className="source-chips">{a.reference_ids_used.map(r=><code key={r}>{r}</code>)}</div></article>)}</div>:<Empty title="A blank page, full of possibility." icon={FileText}>Your report grows here, one validated section at a time.</Empty>}<div className="panel-note"><ShieldCheck size={13}/>SYNTHETIC_DEMONSTRATION · Illustrative reference data, not current provider pricing.</div></section>
        </>}

        {tab==='Drift inspector'&&<>{researchNeedsReview&&<div className="provider-notice"><Workflow size={15}/><span>Research evidence needs attention before a report can be proposed.</span><button className="text-button" onClick={()=>scrollTo('handoffs')}>Inspect research findings<ArrowUpRight size={14}/></button></div>}<div className="review-summary"><ShieldCheck size={20}/><div><strong>Good decisions start with a closer look.</strong><p>{pending} awaiting review · {approved} allowed · {blocked} blocked</p></div><Badge tone="blue">Goal gateway</Badge></div><div className="inspector-grid"><section className="panel"><div className="panel-heading"><h2>Action proposals</h2><span className="count-label">{filteredActions.length}</span></div>{!filteredActions.length?<Empty title={search?'No matching actions':'Nothing to review yet'} icon={Search}>{search?'Try a different search.':'Run a session step to generate the first proposal.'}</Empty>:filteredActions.map(a=><button className={`action-item ${a.id===inspected?.id?'selected':''}`} key={a.id} onClick={()=>{setSelected(a.id);setReviewReason('');}}><div><strong>{a.body.topic.toLowerCase()}</strong><Badge tone={a.decision==='ALLOW'?'green':a.decision==='BLOCK'?'red':'amber'}>{a.resolution||a.decision}</Badge></div><p>{a.body.section_id.replaceAll('_',' ')}</p><small>{stamp(a.created_at)}</small></button>)}</section><section className="panel">{inspected?<><div className="panel-heading"><h2>Proposal details</h2><Badge tone={inspected.decision==='ALLOW'?'green':inspected.decision==='BLOCK'?'red':'amber'}>{inspected.resolution||inspected.decision}</Badge></div><div className="detail-content"><div className="detail-meta"><span>Report agent</span><span>{inspected.body.milestone_id}</span><span>Contract v{inspected.body.contract_version}</span></div><h2 className="proposal-title">{inspected.body.section_id.replaceAll('_',' ')}</h2><p className="proposal-text">{inspected.body.content}</p><h3>Declared effects</h3><pre className="declared-effects">{JSON.stringify(inspected.action?.declared_effects||{},null,2)}</pre><h3>Validation decision</h3><p>{inspected.reason}</p>{inspected.resolution&&<p>User disposition: {inspected.resolution}{inspected.review?.reason?` — ${inspected.review.reason}`:''}</p>}<h3>Agent rationale</h3><p>{inspected.body.rationale}</p><h3>Source references</h3><div>{inspected.body.reference_ids_used.map(r=>{const ref=sourceReferences.find(x=>x.reference_id===r);return <div className="source-evidence" key={r}><code>{r}</code><p>{ref?.summary||'Source is unavailable under the current approved contract.'}</p>{ref&&<small>{ref.label}</small>}</div>;})}</div><h3>Inference provenance</h3><InferenceDetails inference={inspected.inference}/>{inspected.decision==='REVIEW'&&!inspected.resolution&&<><p className="review-note">This proposal remains uncommitted until you approve its claims and evidence. Mandatory policy failures cannot be overridden.</p><div className="review-controls"><Button variant="danger" disabled={busy||running} onClick={()=>void resolveReview(inspected,'REJECT')}><X size={14}/>Reject proposal</Button><label>Review explanation<textarea aria-label="Review explanation" value={reviewReason} maxLength={2000} rows={3} onChange={e=>setReviewReason(e.target.value)} placeholder="Explain why the claims are supported and within scope."/></label><Button disabled={busy||running||!config?.review_approval_available||reviewReason.trim().length<10} onClick={()=>void resolveReview(inspected,'APPROVE')}><Check size={14}/>Approve reviewed content</Button></div></>}</div></>:<Empty title="Every decision has a reason." icon={ShieldCheck}>Select an action to inspect its content, sources, and validation.</Empty>}</section></div></>}

        {tab==='History & evaluation'&&<>{project.legacy_archive_available&&<div className="provider-notice"><History size={15}/><span>Previous dashboard data was preserved. <a href={`/api/projects/${project.id}/archive`} target="_blank" rel="noreferrer">View the archive</a>.</span></div>}<div className="work-grid"><section className="panel"><div className="panel-heading"><h2><GitBranch size={16}/>Contract history</h2><Badge>{contracts.length} versions</Badge></div><div className="contract-list">{contracts.map(c=><div key={c.version}><span className="version-icon">v{c.version}</span><div><strong>{c.version===project.contract.version?'Active approved contract':'Previous approved contract'}</strong><p>{c.approved_topics.map(t=>t.toLowerCase()).join(' · ')}</p></div><ShieldCheck size={17}/></div>)}</div></section><section className="panel"><div className="panel-heading"><h2><Activity size={16}/>Evaluation</h2><Badge>{evaluations.length} recorded runs</Badge></div><Evaluation runs={evaluations}/></section></div><section className="panel history-panel"><div className="panel-heading"><h2><History size={16}/>Project timeline</h2><span className="subtle">{events.length} events</span></div><div className="timeline">{events.map(e=><div key={e.id}><span className={`event-dot ${e.kind.includes('FAIL')?'red':''}`}/><div><div className="timeline-event-top"><Badge tone={e.kind.includes('FAIL')||e.kind.includes('BLOCK')?'red':e.kind.includes('REVIEW')?'amber':'muted'}>{e.kind.replaceAll('_',' ')}</Badge><small>{stamp(e.created_at)}</small></div><strong>{e.message}</strong>{e.kind==='INFERENCE_COMPLETED'&&<InferenceDetails inference={e.body}/>}</div></div>)}</div></section></>}
        </>}

        {config?.hosted_inputs&&<details className="provider-notice provider-disclosure"><summary><Radio size={13}/><span>About your inference provider</span><ChevronDown size={13}/></summary><p>Hosted report inference sends the objective, constraints, supplied fixture, and previous validation feedback to Groq. Durable project state stays in SQLite. Specialist sessions in this interface use local Ollama.</p></details>}
        <footer><span><Workflow size={13}/>A clear goal. Every step of the way.</span><span>TETHER WORKSPACE <span className="dot"/>LOCAL STORAGE</span></footer>
      </main>
    </div>

    <dialog ref={dialogRef} className="modal" onCancel={e=>{if(busy)e.preventDefault();else setCreateOpen(false);}} onClick={e=>{if(e.target===dialogRef.current&&!busy)setCreateOpen(false);}} aria-labelledby="create-title"><div className="modal-header"><span className="node-icon violet"><Sparkles size={21}/></span><button className="icon-button" disabled={busy} aria-label="Close dialog" onClick={()=>setCreateOpen(false)}><X size={17}/></button></div><div className="modal-intro"><h2 id="create-title">Start with a clear goal.</h2><p>A new project. A little direction. Your next step forward.</p></div><form onSubmit={e=>{e.preventDefault();void create();}}><label>Project name<input autoFocus required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label><label>What would you like to accomplish?<textarea required minLength={10} maxLength={2000} rows={4} value={objective} onChange={e=>setObjective(e.target.value)}/></label><p className="form-note"><ShieldCheck size={14}/>Uses the cloud-comparison workflow and supplied synthetic references. Custom workflow templates are a later extension.</p><Button disabled={busy||!name.trim()||objective.trim().length<10} type="submit">{busy?<LoaderCircle size={15} className="spin"/>:<Plus size={15}/>}Create project<ArrowRight size={15}/></Button>{error&&<p className="form-error" role="alert">{error}</p>}</form></dialog>
  </div>;
}
