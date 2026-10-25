'use client';
import {useState} from 'react';
import {Button} from '@/components/ui/button';
import {Badge} from '@/components/workspace';
import {api} from '@/lib/api';
import type {Contract} from '@/lib/types';

type Preview={contract:Contract;examples:{title:string;proposal:string;decision:string;reasons:string[]}[]};
export function DemoGuide({onCreate}:{onCreate:()=>void}){
  const [preview,setPreview]=useState<Preview|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function rehearse(){setBusy(true);setError('');try{setPreview(await api<Preview>('/demo/safety-examples'));}catch(e){setError(e instanceof Error?e.message:'Could not load examples');}finally{setBusy(false);}}
  return <section className="panel demo-guide"><details><summary>Presenting Tether? Open the workflow demo guide</summary><div className="detail-content"><h2>Show the full workflow</h2><p>General requests have one draft milestone. The cloud demo has four: costs → deployment → comparison → recommendation.</p><p>Choose Research + Report to show two sequential specialists using the same approved contract. Exact quotations may save automatically; comparison and recommendation pause for human review. Approving one advances to the next milestone.</p><Button onClick={onCreate}>Set up four-milestone demo</Button><h3>Rehearse safety decisions without API usage</h3><p>These scripted proposals run through the real validator against a separate sample contract. They do not run agents, change your project, or save output.</p><Button variant="outline" disabled={busy} onClick={()=>void rehearse()}>{busy?'Checking examples…':'Show ALLOW / REVIEW / BLOCK'}</Button>{error&&<p role="alert">{error}</p>}{preview&&<div className="demo-examples"><p><strong>Sample contract v{preview.contract.version}</strong> · Supplied evidence only · No unapproved scope</p>{preview.examples.map(e=><article key={e.title}><h3><Badge tone={e.decision==='BLOCK'?'red':e.decision==='REVIEW'?'amber':'green'}>{e.decision}</Badge> {e.title}</h3><p>{e.reasons.join(' ')}</p><p>{e.decision==='ALLOW'?'May be saved automatically.':e.decision==='REVIEW'?'Human review is required before saving.':'Cannot be approved or saved. Remove the scope violation or explicitly approve a contract change first.'}</p><details><summary>Inspect scripted proposal</summary><pre className="declared-effects">{e.proposal}</pre></details></article>)}</div>}</div></details></section>;
}

export function SharedContract({contract,specialists}:{contract:Contract;specialists:boolean}){
  return <section className="panel shared-contract"><details><summary>Approved contract v{contract.version} · {specialists?'Shared by Research and Report':'Used by the response agent and validator'}</summary><div className="detail-content"><p><strong>Goal:</strong> {contract.objective}</p><p><strong>Approved scope:</strong> {contract.approved_topics.join(', ')}</p>{contract.constraints.map(c=><p key={c.id}><strong>{c.id} · {c.severity}:</strong> {c.type.replaceAll('_',' ')} — {String(c.value)}</p>)}<p>{specialists?'Research receives this contract and scoped evidence → handoff validation checks its findings → Report receives the same contract and accepted findings → action validation checks the proposed write.':'The response is checked against this approved goal before it can be saved.'}</p><p>Agents propose content. Contract changes require your approval.</p><details><summary>Inspect contract JSON</summary><pre className="declared-effects">{JSON.stringify(contract,null,2)}</pre></details></div></details></section>;
}
