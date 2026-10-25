"""HTTP integration tests against the actual merged engine; model calls are doubles."""
import json
import os
import sqlite3
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from backend import main as api
from backend.store import prepare_database, AppStore
from engine.schemas import AgentAction, AgentHandoff


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv('TETHER_DB', str(tmp_path / 'app.sqlite3'))
    with TestClient(api.app, headers={'Origin':'http://testserver'}) as client:
        client.get('/api/health')
        yield client


def project_session(web, mode='single'):
    response = web.post('/api/projects',json={})
    assert response.status_code == 201, response.text
    project = response.json()['id']
    response = web.post(f'/api/projects/{project}/sessions',json={'mode':mode})
    assert response.status_code == 201, response.text
    return project,response.json()['id']


class Model:
    def __init__(self, *, topic=None, prose=False, fail=False, entered=None, release=None):
        self.calls=[]
        self.count=0
        self.topic=topic
        self.prose=prose
        self.fail=fail
        self.entered,self.release=entered,release

    def generate(self, schema, system, prompt):
        data=json.loads(prompt)
        self.count+=1
        self.calls.append({'provider':'ollama','model':'qwen3:4b','attempt':1,'schema_valid':not self.fail,'elapsed_seconds':.1,'fallback_from':'groq','fallback_reason':'missing_credentials','request':{'secret':'must not persist'}})
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail:
            self.calls[-1]['error_kind']='connection_or_timeout'
            raise RuntimeError('simulated failure')
        ref=data['references'][0]
        if schema is AgentHandoff:
            return AgentHandoff.model_validate({'handoff_id':data['handoff_id'],'project_id':data['project_id'],
                'session_id':data['session_id'],'contract_version':data['contract_version'],
                'milestone_id':data['milestone_id'],'topic':data['topic'],
                'findings':[{'fact_id':'F1','provider':ref['provider'],'reference_id':ref['reference_id'],'summary':ref['summary']}],
                'next_action':'Draft supported section'})
        contract=data['contract']
        milestone=next(m for m in contract['milestones'] if m['status']=='ACTIVE')
        section=data['requested_section_id']
        existing=section in data['existing_sections']
        return AgentAction.model_validate({'action_id':data['action_id'],'project_id':contract['project_id'],
            'session_id':data['session_id'],'contract_version':contract['version'],
            'milestone_id':milestone['id'],'topic':self.topic or milestone['allowed_topics'][0],
            'declared_effects':{'sections_created':[] if existing else [section],'sections_modified':[section] if existing else [],
                'topics_introduced':[self.topic or milestone['allowed_topics'][0]], 'reference_ids_used':[ref['reference_id']],
                'numerical_claims':[{'value':n,'reference_id':ref['reference_id'],'quote':ref['summary']} for n in ref['numerical_values']]},
            'arguments':{'section_id':section,'content':f"SYNTHETIC_DEMONSTRATION [{ref['reference_id']}] {ref['summary']}"+(' Best provider.' if self.prose else '')},
            'rationale':'Supports active milestone'})


def test_real_engine_commit_replay_and_history(web):
    project,session=project_session(web)
    model=Model()
    with patch.object(api,'create_client',return_value=model):
        first=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-HTTP'})
        assert first.status_code==200,first.text
        assert first.json()['committed']
        replay=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-HTTP'})
    assert replay.json()['replayed'] and model.count==1
    state=web.get(f'/api/projects/{project}').json()
    assert len(state['artifacts'])==1
    assert state['contract']['milestones'][0]['status']=='ACTIVE'
    assert state['actions'][0]['inference']['attempts'][0]['provider']=='ollama'
    timeline=web.get(f'/api/projects/{project}/timeline').json()
    kinds=[e['kind'] for e in reversed(timeline)]
    assert kinds.index('INFERENCE_COMPLETED')<kinds.index('ACTION_COMMITTED')
    assert 'must not persist' not in json.dumps(timeline)


def test_policy_block_never_commits_or_retries_provider(web):
    project,session=project_session(web)
    model=Model(topic='SECURITY')
    with patch.object(api,'create_client',return_value=model) as factory:
        result=web.post(f'/api/sessions/{session}/step',json={})
    assert result.json()['validation']['decision']=='BLOCK'
    assert model.count==1 and factory.call_count==1
    assert web.get(f'/api/projects/{project}/report').json()['sections']==[]
    assert web.get(f'/api/sessions/{session}').json()['status']=='BLOCKED'


def test_review_cannot_be_approved_but_can_be_rejected(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model(prose=True)):
        result=web.post(f'/api/sessions/{session}/step',json={}).json()
    assert result['validation']['decision']=='REVIEW'
    key=result['action']['action_id']
    assert web.post(f'/api/actions/{key}/decision',json={'decision':'APPROVE'}).status_code==409
    assert web.get(f'/api/projects/{project}/report').json()['sections']==[]
    assert web.post(f'/api/actions/{key}/decision',json={'decision':'REJECT'}).status_code==200
    assert web.get(f'/api/projects/{project}').json()['actions'][0]['resolution']=='REJECTED'


def test_failure_records_attempts_and_retries_same_key(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model(fail=True)):
        result=web.post(f'/api/sessions/{session}/step',json={})
    assert result.status_code==503
    info=web.get(f'/api/sessions/{session}').json()
    assert info['status']=='FAILED'
    key=info['pending_action']
    events=web.get(f'/api/projects/{project}/timeline').json()
    assert any(e['kind']=='INFERENCE_COMPLETED' for e in events)
    with patch.object(api,'create_client',return_value=Model()):
        retried=web.post(f'/api/sessions/{session}/step',json={})
    assert retried.json()['action']['action_id']==key
    assert len(web.get(f'/api/projects/{project}').json()['inference'][0]['attempts'])==2


def test_explicit_progress_and_immutable_scope_versions(web):
    project,session=project_session(web)
    assert web.post(f'/api/projects/{project}/milestones/M1/complete').status_code==409
    with patch.object(api,'create_client',return_value=Model()):
        assert web.post(f'/api/sessions/{session}/step',json={}).json()['committed']
    assert web.post(f'/api/projects/{project}/milestones/M1/complete').status_code==200
    change=web.post(f'/api/projects/{project}/changes',json={'topic':'SERVERLESS'}).json()['id']
    assert web.post(f'/api/changes/{change}/decision',json={'decision':'APPROVE'}).json()['version']==2
    versions=web.get(f'/api/projects/{project}/contracts').json()
    assert len(versions)==2 and 'SERVERLESS' not in versions[1]['approved_topics']
    state=web.get(f'/api/projects/{project}').json()
    assert [m['status'] for m in state['contract']['milestones']][:2]==['COMPLETED','ACTIVE']
    assert versions[1]['milestones'][0]['status']=='ACTIVE'


def test_operator_boundary_and_forged_actor_rejected(web):
    web.cookies.clear()
    assert web.post('/api/projects',json={}).status_code==403
    web.get('/api/health')
    assert web.post('/api/projects',json={},headers={'Origin':'https://untrusted.example'}).status_code==403
    assert web.post('/api/projects',json={'actor':'agent'}).status_code==422


def test_cross_session_action_key_cannot_replay(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model()):
        web.post(f'/api/sessions/{session}/step',json={'action_id':'A-BOUND'})
    second=web.post(f'/api/projects/{project}/sessions',json={}).json()['id']
    assert web.post(f'/api/sessions/{second}/step',json={'action_id':'A-BOUND'}).status_code==409


def test_concurrent_steps_generate_once(web):
    project,session=project_session(web)
    entered,release=threading.Event(),threading.Event()
    model=Model(entered=entered,release=release)
    with patch.object(api,'create_client',return_value=model), ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(web.post,f'/api/sessions/{session}/step',json={'action_id':'A-RACE'})
        assert entered.wait(5)
        try:
            second=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-RACE'})
            assert second.status_code==409
        finally:
            release.set()
        assert first.result().status_code==200
    assert model.count==1


def test_specialist_handoff_uses_configured_client_and_audits_before_commit(web):
    project,session=project_session(web,mode='specialists')
    model=Model()
    with patch.object(api,'create_client',return_value=model) as factory:
        result=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-SPECIAL'})
    assert result.status_code==200,result.text
    assert result.json()['step']['committed']
    factory.assert_called_once_with()
    assert model.count==2
    h=web.get(f'/api/sessions/{session}/handoffs').json()['handoffs']
    assert h[0]['validation']['decision']=='ALLOW'
    timeline=list(reversed(web.get(f'/api/projects/{project}/timeline').json()))
    kinds=[e['kind'] for e in timeline]
    assert kinds.count('INFERENCE_COMPLETED')==2
    assert max(i for i,k in enumerate(kinds) if k=='INFERENCE_COMPLETED')<kinds.index('ACTION_COMMITTED')


def test_recovery_replays_without_model_after_restart(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model()):
        web.post(f'/api/sessions/{session}/step',json={'action_id':'A-RESTART'})
    with TestClient(api.app,headers={'Origin':'http://testserver'}) as restarted:
        restarted.get('/api/health')
        with patch.object(api,'create_client',side_effect=AssertionError('Must not generate')):
            assert restarted.post(f'/api/sessions/{session}/step',json={'action_id':'A-RESTART'}).json()['replayed']
        assert len(restarted.get(f'/api/projects/{project}/report').json()['sections'])==1


def test_specialist_retry_resumes_saved_research(web):
    project,session=project_session(web,mode='specialists')
    class Interrupted(Model):
        def generate(self, schema, system, prompt):
            if schema is AgentAction:
                raise RuntimeError('Report interrupted')
            return super().generate(schema,system,prompt)
    with patch.object(api,'create_client',return_value=Interrupted()):
        assert web.post(f'/api/sessions/{session}/step',json={'action_id':'A-RESUME'}).status_code==503
    assert web.get(f'/api/sessions/{session}').json()['checkpoint']['state']=='HANDOFF'
    with TestClient(api.app,headers={'Origin':'http://testserver'}) as restarted:
        restarted.get('/api/health')
        report=Model()
        with patch.object(api,'create_client',return_value=report):
            result=restarted.post(f'/api/sessions/{session}/step',json={})
        assert result.status_code==200,result.text
        assert result.json()['step']['committed'] and result.json()['handoff']['replayed']
        assert report.count==1


def test_legacy_database_is_backed_up_and_archived(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    con=sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE projects(id TEXT,name TEXT,created_at TEXT);
    CREATE TABLE contracts(project_id TEXT,version INTEGER,body TEXT);
    CREATE TABLE sessions(id TEXT,project_id TEXT,status TEXT,created_at TEXT);
    CREATE TABLE actions(id TEXT,project_id TEXT,body TEXT);
    CREATE TABLE artifacts(action_id TEXT,project_id TEXT,body TEXT);
    CREATE TABLE changes(id TEXT,project_id TEXT);
    CREATE TABLE events(id INTEGER,project_id TEXT,body TEXT);
    """)
    template=json.loads((api.ROOT/'scenarios/cloud_comparison.json').read_text())
    template['project_id']='legacy'
    con.execute('INSERT INTO projects VALUES(?,?,?)',('legacy','Old project','2026-10-24'))
    con.execute('INSERT INTO contracts VALUES(?,?,?)',('legacy',1,json.dumps(template)))
    con.execute('INSERT INTO artifacts VALUES(?,?,?)',('OLD-A','legacy','old report stays archived'))
    con.commit();con.close()
    prepare_database(path)
    current=AppStore(path)
    try:
        current.import_legacy();current.import_legacy()
        assert current.current_contract('legacy').version==1
        assert current.archive('legacy')['artifacts'][0]['body']=='old report stays archived'
        assert current.sections('legacy')=={}
        assert path.with_name('legacy.pre-engine.sqlite3').exists()
    finally:
        current.close()


def test_telemetry_redacts_credentials():
    from backend.inference import public_attempts
    with patch.dict(os.environ,{'GROQ_API_KEY':'private-test-key'}):
        value=json.dumps(public_attempts([{'provider':'groq','request':'hidden prompt','fallback_reason':'private-test-key gsk_secret123'}]))
    assert 'private-test-key' not in value and 'gsk_secret123' not in value and 'hidden prompt' not in value

def test_explicit_review_approval_commits_and_survives_replay(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model(prose=True)):
        proposal=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-REVIEW'}).json()
    assert not proposal['committed']
    approved=web.post('/api/actions/A-REVIEW/decision',json={'decision':'APPROVE','reason':'Verified the cited evidence and startup recommendation.'})
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='APPROVED'
    state=web.get(f'/api/projects/{project}').json()
    assert state['actions'][0]['resolution']=='APPROVED'
    assert state['actions'][0]['decision']=='REVIEW' and state['actions'][0]['committed']
    assert len(state['artifacts'])==1
    with patch.object(api,'create_client',side_effect=AssertionError('Replay must not infer')):
        replay=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-REVIEW'}).json()
    assert replay['replayed'] and replay['committed']
    assert web.post('/api/actions/A-REVIEW/decision',json={'decision':'REJECT'}).status_code==409


def test_review_approval_cannot_bypass_new_contract(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model(prose=True)):
        web.post(f'/api/sessions/{session}/step',json={'action_id':'A-STALE'})
    change=web.post(f'/api/projects/{project}/changes',json={}).json()['id']
    assert web.post(f'/api/changes/{change}/decision',json={'decision':'APPROVE'}).status_code==200
    result=web.post('/api/actions/A-STALE/decision',json={'decision':'APPROVE','reason':'Reviewed against the previous version.'})
    assert result.status_code==409 and 'mandatory' in result.json()['detail']
    assert web.get(f'/api/projects/{project}/report').json()['sections']==[]

def test_metrics_reads_persisted_measured_runs_only(web):
    from engine.evaluator import save_evaluation
    project,session=project_session(web)
    assert web.get(f'/api/projects/{project}/metrics').json()['runs']==[]
    with api.store() as current:
        save_evaluation(current,{'id':'E-MEASURED','project_id':project,'mode':'tether','status':'FAILED',
                                 'kind':'PROPOSAL_EVALUATION','error':'InferenceError'})
    data=web.get(f'/api/projects/{project}/metrics').json()
    assert data['runs'][0]['id']=='E-MEASURED'
    assert data['runs'][0]['status']=='FAILED'
    assert web.get(f'/api/projects/{project}/report').json()['sections']==[]

def test_sources_are_available_for_human_review_and_respect_scope(web):
    project,session=project_session(web)
    records=web.get(f'/api/projects/{project}/references').json()
    assert records and all(r['label']=='SYNTHETIC_DEMONSTRATION' for r in records)
    assert 'SERVERLESS' not in {r['topic'] for r in records}
    change=web.post(f'/api/projects/{project}/changes',json={}).json()['id']
    web.post(f'/api/changes/{change}/decision',json={'decision':'APPROVE'})
    assert 'SERVERLESS' in {r['topic'] for r in web.get(f'/api/projects/{project}/references').json()}


def test_uncertain_research_can_be_rejected_then_replanned(web):
    project,session=project_session(web,mode='specialists')
    class Uncertain(Model):
        def generate(self,schema,system,prompt):
            output=super().generate(schema,system,prompt)
            return output.model_copy(update={'unresolved_questions':['Evidence needs inspection']})
    with patch.object(api,'create_client',return_value=Uncertain()):
        first=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-UNCERTAIN'})
    assert first.json()['state']=='AWAITING_REVIEW'
    assert web.post(f'/api/sessions/{session}/pending/decision',json={'decision':'APPROVE'}).status_code==409
    assert web.post(f'/api/sessions/{session}/pending/decision',json={'decision':'REJECT'}).status_code==200
    assert web.get(f'/api/sessions/{session}').json()['pending_action'] is None
    assert web.get(f'/api/sessions/{session}/handoffs').json()['handoffs'][0]['resolution']=='REJECTED'
    assert web.post(f'/api/sessions/{session}/step',json={'action_id':'A-UNCERTAIN'}).status_code==409
    with patch.object(api,'create_client',return_value=Model()):
        fresh=web.post(f'/api/sessions/{session}/step',json={})
    assert fresh.json()['step']['committed']
    assert fresh.json()['step']['action']['action_id']!='A-UNCERTAIN'

def test_demo_reset_preserves_original_history(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model()):
        web.post(f'/api/sessions/{session}/step',json={})
    old=web.get(f'/api/projects/{project}').json()
    reset=web.post('/api/demo/reset',json={'project_id':project})
    assert reset.status_code==201,reset.text
    assert reset.json()['history_preserved']
    fresh=web.get('/api/projects/'+reset.json()['id']).json()
    assert fresh['id']!=project and fresh['contract']['version']==1
    assert fresh['actions']==[] and fresh['artifacts']==[] and fresh['sessions']==[]
    assert web.get(f'/api/projects/{project}').json()['artifacts']==old['artifacts']

def test_complete_merged_workflow_through_v2_and_all_milestones(web):
    """Exercise the entire control flow with explicit test doubles, not model-quality claims."""
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model()):
        assert web.post(f'/api/sessions/{session}/step',json={'action_id':'A-FULL-COST'}).json()['committed']
    assert web.post(f'/api/projects/{project}/milestones/M1/complete').status_code==200
    drift_session=web.post(f'/api/projects/{project}/sessions',json={}).json()['id']
    with patch.object(api,'create_client',return_value=Model(topic='SECURITY')):
        drift=web.post(f'/api/sessions/{drift_session}/step',json={}).json()
    assert drift['validation']['decision']=='BLOCK' and not drift['committed']
    change=web.post(f'/api/projects/{project}/changes',json={}).json()['id']
    assert web.post(f'/api/changes/{change}/decision',json={'decision':'APPROVE'}).json()['version']==2
    with TestClient(api.app,headers={'Origin':'http://testserver'}) as resumed:
        resumed.get('/api/health')
        with patch.object(api,'create_client',side_effect=AssertionError('Historical replay must not infer')):
            assert resumed.post(f'/api/sessions/{session}/step',json={'action_id':'A-FULL-COST'}).json()['replayed']
        for milestone,prose in [('M2',False),('M3',True),('M4',True),('M5',False)]:
            next_session=resumed.post(f'/api/projects/{project}/sessions',json={}).json()['id']
            with patch.object(api,'create_client',return_value=Model(prose=prose)):
                step=resumed.post(f'/api/sessions/{next_session}/step',json={})
            assert step.status_code==200,step.text
            result=step.json()
            assert result['action']['contract_version']==2
            if prose:
                assert result['validation']['decision']=='REVIEW' and not result['committed']
                approved=resumed.post('/api/actions/'+result['action']['action_id']+'/decision',
                    json={'decision':'APPROVE','reason':'Inspected the source quotations and accepted the synthesis.'})
                assert approved.status_code==200,approved.text
            else:
                assert result['committed']
            assert resumed.post(f'/api/projects/{project}/milestones/{milestone}/complete').status_code==200
        final=resumed.get(f'/api/projects/{project}').json()
        assert len(final['artifacts'])==5
        assert all(m['status']=='COMPLETED' for m in final['contract']['milestones'])
        versions=resumed.get(f'/api/projects/{project}/contracts').json()
        assert len(versions)==2 and versions[-1]['milestones'][0]['status']=='ACTIVE'
        assert resumed.post(f'/api/sessions/{next_session}/step',json={}).status_code==409

@pytest.mark.parametrize('primary_kind,local_kind',[
    ('http_429','connection_or_timeout'),
    ('http_401','http_404'),
    ('structured_output_failed_twice','connection_or_timeout'),
])
def test_provider_failure_is_persisted_and_retry_recovers(web,primary_kind,local_kind):
    from engine.llm_client import InferenceError
    class FailedProviders:
        calls=[]
        def generate(self,*args):
            self.calls=[{'provider':'groq','error_kind':primary_kind},
                        {'provider':'ollama','error_kind':local_kind}]
            raise InferenceError('ollama',local_kind)
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=FailedProviders()):
        failed=web.post(f'/api/sessions/{session}/step',json={})
    assert failed.status_code==503
    state=web.get(f'/api/projects/{project}').json()
    assert state['sessions'][0]['failure_reason']==failed.json()['detail']
    assert state['artifacts']==[]
    key=state['sessions'][0]['pending_action']
    model=Model()
    with patch.object(api,'create_client',return_value=model):
        recovered=web.post(f'/api/sessions/{session}/step',json={})
        replay=web.post(f'/api/sessions/{session}/step',json={'action_id':key})
    assert recovered.status_code==200 and recovered.json()['committed']
    assert recovered.json()['action']['action_id']==key
    assert replay.json()['replayed'] and model.count==1
    state=web.get(f'/api/projects/{project}').json()
    assert state['sessions'][0]['failure_reason'] is None
    assert len(state['artifacts'])==1


class CompleteModel(Model):
    """All supplied evidence; synthesis deliberately requires human review."""
    def generate(self, schema, system, prompt):
        result = super().generate(schema, system, prompt)
        data = json.loads(prompt)
        refs = data['references']
        if schema is AgentHandoff:
            return result.model_copy(update={'findings': [
                type(result.findings[0])(fact_id=f'F{i}',provider=r['provider'],reference_id=r['reference_id'],summary=r['summary'])
                for i,r in enumerate(refs)]})
        effects = type(result.declared_effects).model_validate({**result.declared_effects.model_dump(),
            'reference_ids_used':[r['reference_id'] for r in refs],
            'numerical_claims':[
                {'value':n,'reference_id':r['reference_id'],'quote':r['summary']}
                for r in refs for n in r['numerical_values']]})
        content='SYNTHETIC_DEMONSTRATION\n'+'\n'.join(f"{r['summary']} [{r['reference_id']}]" for r in refs)
        if data['topic'] in ('COMPARISON','RECOMMENDATION'):
            content += '\nCompare these providers for a startup.'
        return AgentAction.model_validate({**result.model_dump(), 'declared_effects':effects.model_dump(),
            'arguments':{**result.arguments.model_dump(),'content':content}})


def test_auto_workflow_progress_review_resume_and_complete(web):
    model=CompleteModel()
    with patch.object(api,'create_client',return_value=model) as factory:
        created=web.post('/api/projects',json={'name':'Human project','objective':'Compare startup cloud costs and deployment.', 'auto_start':True,'mode':'specialists'})
        assert created.status_code==201,created.text
        project=created.json()['id']
        state=web.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']=='AWAITING_REVIEW',state['workflow']
        assert [m['status'] for m in state['contract']['milestones']]==['COMPLETED','COMPLETED','ACTIVE','PENDING']
        assert len(state['artifacts'])==2
        # Repeated resume cannot generate past an unresolved review.
        count=model.count
        assert web.post(f'/api/projects/{project}/workflow',json={}).status_code==202
        assert model.count==count
        for _ in range(2):
            state=web.get(f'/api/projects/{project}').json()
            action=next(a for a in state['actions'] if a['decision']=='REVIEW' and not a['resolution'])
            approved=web.post(f"/api/actions/{action['id']}/decision",json={'decision':'APPROVE','reason':'Compared all supplied synthetic source quotations and supported claims.'})
            assert approved.status_code==200,approved.text
        state=web.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']=='COMPLETED',state['workflow']
        assert len(state['artifacts'])==4
        assert [a['milestone_id'] for a in state['artifacts']]==['M1','M2','M3','M4']
        assert all(m['status']=='COMPLETED' for m in state['contract']['milestones'])
        assert factory.call_args.args==()


def test_automatic_workflow_stops_on_block_or_provider_failure(web):
    for model,expected in [(Model(topic='SECURITY'),'BLOCKED'),(Model(fail=True),'FAILED')]:
        project=web.post('/api/projects',json={}).json()['id']
        with patch.object(api,'create_client',return_value=model):
            result=web.post(f'/api/projects/{project}/workflow',json={'mode':'single'})
        assert result.status_code==202
        state=web.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']==expected,state['workflow']
        assert not state['artifacts']
        assert model.count==1


def test_automatic_workflow_does_not_complete_partial_evidence(web):
    project=web.post('/api/projects',json={}).json()['id']
    with patch.object(api,'create_client',return_value=Model()):
        web.post(f'/api/projects/{project}/workflow',json={'mode':'single'})
    state=web.get(f'/api/projects/{project}').json()
    assert state['workflow']['state']=='NEEDS_EVIDENCE'
    assert state['contract']['milestones'][0]['status']=='ACTIVE'
    with patch.object(api,'create_client',return_value=CompleteModel()):
        web.post(f'/api/projects/{project}/workflow',json={})
    state=web.get(f'/api/projects/{project}').json()
    assert state['workflow']['state']=='AWAITING_REVIEW',state['workflow']
    assert state['contract']['milestones'][0]['status']=='COMPLETED'


def test_auto_workflow_pause_duplicate_claim_and_resume(web):
    project=web.post('/api/projects',json={}).json()['id']
    entered,release=threading.Event(),threading.Event()
    model=CompleteModel(entered=entered,release=release)
    with patch.object(api,'create_client',return_value=model),ThreadPoolExecutor() as pool:
        task=pool.submit(web.post,f'/api/projects/{project}/workflow',json={'mode':'single'})
        assert entered.wait(5)
        assert web.post(f'/api/projects/{project}/workflow',json={}).status_code==409
        assert web.post(f'/api/projects/{project}/sessions',json={}).status_code==409
        assert web.post(f'/api/projects/{project}/workflow/pause',json={}).status_code==200
        release.set()
        assert task.result().status_code==202
        state=web.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']=='PAUSED'
        assert len(state['actions'])==1
        assert state['contract']['milestones'][0]['status']=='ACTIVE'
        web.post(f'/api/projects/{project}/workflow',json={})
    state=web.get(f'/api/projects/{project}').json()
    assert state['workflow']['state']=='AWAITING_REVIEW'
    assert state['contract']['milestones'][0]['status']=='COMPLETED'


def test_restart_pauses_workflow_without_inference(web):
    project=web.post('/api/projects',json={}).json()['id']
    with patch.object(api,'drive_workflow'):
        web.post(f'/api/projects/{project}/workflow',json={})
    with TestClient(api.app, headers={'Origin':'http://testserver'}) as restarted:
        state=restarted.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']=='PAUSED'
        assert not state['actions']
        assert 'restarted' in state['workflow']['message']


def test_rejected_review_pauses_then_can_generate_again(web):
    model=CompleteModel()
    with patch.object(api,'create_client',return_value=model):
        project=web.post('/api/projects',json={'auto_start':True,'mode':'single'}).json()['id']
        state=web.get(f'/api/projects/{project}').json()
        action=state['actions'][0]['id']
        web.post(f'/api/actions/{action}/decision',json={'decision':'REJECT'})
        state=web.get(f'/api/projects/{project}').json()
        assert state['workflow']['state']=='PAUSED'
        assert len(state['artifacts'])==2
        web.post(f'/api/projects/{project}/workflow',json={'mode':'single'})
    state=web.get(f'/api/projects/{project}').json()
    assert state['workflow']['state']=='AWAITING_REVIEW'
    assert len(state['actions'])==4
    assert state['actions'][0]['id']!=action


def test_new_workflow_cannot_ignore_existing_review(web):
    project,session=project_session(web)
    with patch.object(api,'create_client',return_value=Model(prose=True)):
        web.post(f'/api/sessions/{session}/step',json={})
    assert web.post(f'/api/projects/{project}/workflow',json={}).status_code==409


class DraftModel:
    def __init__(self):
        self.calls = []
        self.prompts = []

    def generate(self, schema, system, prompt):
        self.prompts.append(json.loads(prompt))
        return schema(content='UNVERIFIED_DRAFT A launch plan tailored to your request.',
                      rationale='Addresses the requested launch plan; assumptions need review.')


def test_general_request_review_feedback_and_completion(web):
    model = DraftModel()
    with patch.object(api, 'create_client', return_value=model):
        response = web.post('/api/projects', json={'name':'Launch', 'kind':'draft',
            'objective':'Write a concise launch plan for a gardening app.', 'auto_start':True})
        assert response.status_code == 201, response.text
        project = response.json()['id']
        view = web.get(f'/api/projects/{project}').json()
        assert view['workflow']['state'] == 'AWAITING_REVIEW'
        assert view['sessions'][0]['mode'] == 'single'
        action = view['actions'][0]
        assert action['decision'] == 'REVIEW'
        assert not view['artifacts']
        response = web.post(f"/api/actions/{action['id']}/revise", json={'feedback':'Focus the plan on community gardens.'})
        assert response.status_code == 202, response.text
        assert model.prompts[-1]['revision_feedback']['requested_changes'] == 'Focus the plan on community gardens.'
        view = web.get(f'/api/projects/{project}').json()
        pending = next(a for a in view['actions'] if not a['resolution'])
        response = web.post(f"/api/actions/{pending['id']}/decision", json={'decision':'APPROVE','reason':'I checked the plan and accept these assumptions.'})
        assert response.status_code == 200, response.text
        view = web.get(f'/api/projects/{project}').json()
        assert view['workflow']['state'] == 'COMPLETED'
        assert len(view['artifacts']) == 1


def test_safety_rehearsal_uses_validator_without_inference_or_project_writes(web):
    before = web.get('/api/projects').json()
    with patch.object(api, 'create_client', side_effect=AssertionError('No inference in rehearsal')):
        response = web.get('/api/demo/safety-examples')
    assert response.status_code == 200
    body = response.json()
    assert body['provider_calls'] == 0 and not body['persisted']
    assert [e['decision'] for e in body['examples']] == ['ALLOW', 'REVIEW', 'BLOCK']
    assert any('unauthorized topic' in r for r in body['examples'][2]['reasons'])
    assert web.get('/api/projects').json() == before


def test_research_receives_same_full_contract_as_report():
    from engine.research_agent import run_research_agent
    from engine.report_agent import plan_next_action
    from engine.schemas import GoalContract
    contract = GoalContract.model_validate_json((api.ROOT / 'scenarios/cloud_comparison.json').read_text())
    payloads = []
    class Capture:
        def generate(self, schema, system, prompt):
            payloads.append(json.loads(prompt))
            return None
    client = Capture()
    run_research_agent(client, contract, 'S', api.references(), 'H')
    plan_next_action(client, contract, 'S', api.references(), 'A')
    assert payloads[0]['contract'] == payloads[1]['contract'] == contract.model_dump(mode='json')
