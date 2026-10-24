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


def test_specialist_handoff_uses_local_client_and_audits_before_commit(web):
    project,session=project_session(web,mode='specialists')
    model=Model()
    with patch.object(api,'create_client',return_value=model) as factory:
        result=web.post(f'/api/sessions/{session}/step',json={'action_id':'A-SPECIAL'})
    assert result.status_code==200,result.text
    assert result.json()['step']['committed']
    factory.assert_called_once_with('ollama')
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
