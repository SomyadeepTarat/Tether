"""Deterministic lifecycle tests; scripted clients are test doubles, not model evals."""
import json
from pathlib import Path
import pytest
from engine.executor import Store
from engine.schemas import AgentAction, AgentHandoff, GoalContract, GoalChange, Reference
from engine.orchestrator import run_specialist_step
from engine.handoff import validate_handoff

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def setup(tmp_path):
    contract=GoalContract.model_validate_json((ROOT/'scenarios/cloud_comparison.json').read_text())
    refs=[Reference.model_validate(r) for r in json.loads((ROOT/'scenarios/cloud_snapshot.json').read_text())['references']]
    store=Store(tmp_path/'state.db')
    store.create_goal_contract(contract)
    store.start_session(contract.project_id,'S1')
    yield store,contract,refs
    store.close()

def change(contract, key='C-1'):
    return GoalChange.model_validate({'change_id':key,'project_id':contract.project_id,'base_version':1,
        'added_topics':['SERVERLESS'], 'added_milestones':[{'id':'M5','title':'Compare serverless',
        'allowed_topics':['SERVERLESS'],'status':'PENDING'}], 'rationale':'User requested serverless comparison'})

def handoff(contract, refs, action='A1', session='S1', **updates):
    return AgentHandoff.model_validate({
        'handoff_id':action+':research','project_id':contract.project_id,'session_id':session,
        'contract_version':contract.version,'milestone_id':'M1','topic':'COST',
        'findings':[{'fact_id':'F1','provider':refs[0].provider,'reference_id':refs[0].reference_id,'summary':refs[0].summary}],
        'next_action':'Draft supported cost section', **updates})

def action(contract, refs, key='A1', session='S1'):
    r=refs[0]
    return AgentAction.model_validate({'action_id':key,'project_id':contract.project_id,'session_id':session,
        'contract_version':contract.version,'milestone_id':'M1','topic':'COST',
        'declared_effects':{'sections_created':['cost'],'sections_modified':[], 'topics_introduced':['COST'],
            'reference_ids_used':[r.reference_id], 'numerical_claims':[{'value':'30','reference_id':r.reference_id,'quote':r.summary}]},
        'arguments':{'section_id':'cost','content':f'SYNTHETIC_DEMONSTRATION\n[{r.reference_id}] {r.summary}'},
        'rationale':'Supports costs'})

class ScriptedClient:
    def __init__(self,*outputs): self.outputs=list(outputs); self.count=0
    def generate(self,*args):
        self.count+=1
        output=self.outputs.pop(0)
        if isinstance(output,Exception): raise output
        return output

def test_approval_is_separate_immutable_and_idempotent(setup):
    s,c,refs=setup
    proposal=change(c)
    s.propose_goal_change(proposal)
    assert s.current_contract(c.project_id).version==1
    s.decide_goal_change(proposal.change_id,approve=True,actor='authenticated-user')
    versions=s.contracts(c.project_id)
    assert len(versions)==2 and versions[0]==c
    assert versions[1].constraints==c.constraints
    assert versions[1].approved_topics[-1]=='SERVERLESS'
    assert versions[1].milestones[-1].id=='M5'
    s.decide_goal_change(proposal.change_id,approve=True,actor='authenticated-user')
    assert len(s.contracts(c.project_id))==2
    with pytest.raises(ValueError,match='final'):
        s.decide_goal_change(proposal.change_id,approve=False,actor='authenticated-user')

def test_rejection_and_missing_actor(setup):
    s,c,refs=setup
    s.propose_goal_change(change(c))
    with pytest.raises(ValueError,match='actor'):
        s.decide_goal_change('C-1',approve=True,actor=' ')
    s.decide_goal_change('C-1',approve=False,actor='user')
    assert s.current_contract(c.project_id).version==1

@pytest.mark.parametrize('patch',[
    {'base_version':2}, {'added_topics':['COST']},
    {'added_milestones':[{'id':'M1','title':'Replace','allowed_topics':['SERVERLESS'],'status':'PENDING'}]},
    {'added_milestones':[{'id':'M5','title':'Skip','allowed_topics':['SERVERLESS'],'status':'COMPLETED'}]},
    {'added_topics':['SERVERLESS','SERVERLESS']},
])
def test_invalid_scope_changes_rejected(setup,patch):
    s,c,refs=setup
    data={**change(c).model_dump(mode='json'),**patch}
    with pytest.raises(ValueError): s.propose_goal_change(GoalChange.model_validate(data))
    assert s.current_contract(c.project_id).version==1

def test_competing_stale_approval_rolls_back(setup):
    s,c,refs=setup
    s.propose_goal_change(change(c,'C-1'))
    s.propose_goal_change(change(c,'C-2'))
    s.decide_goal_change('C-1',approve=True,actor='user')
    with pytest.raises(ValueError,match='stale'):
        s.decide_goal_change('C-2',approve=True,actor='user')
    assert s.goal_change('C-2')['status']=='PENDING'
    assert len(s.contracts(c.project_id))==2

def test_milestone_progress_requires_artifact_and_preserves_snapshot(setup):
    s,c,refs=setup
    with pytest.raises(ValueError,match='supporting artifact'):
        s.complete_milestone(c.project_id,'M1',actor='user')
    s.commit_action(action(c,refs),refs)
    effective=s.complete_milestone(c.project_id,'M1',actor='user')
    assert [m.status for m in effective.milestones][:2]==['COMPLETED','ACTIVE']
    assert s.current_contract(c.project_id)==c
    before=len(s.timeline(c.project_id))
    s.complete_milestone(c.project_id,'M1',actor='user')
    assert len(s.timeline(c.project_id))==before
    assert not s.commit_action(action(c,refs,'A2'),refs).committed

def test_scope_approval_keeps_execution_progress(setup):
    s,c,refs=setup
    s.commit_action(action(c,refs),refs)
    s.complete_milestone(c.project_id,'M1',actor='user')
    s.propose_goal_change(change(c))
    s.decide_goal_change('C-1',approve=True,actor='user')
    effective=s.effective_contract(c.project_id)
    assert effective.version==2
    assert effective.milestones[0].status=='COMPLETED'
    assert effective.milestones[1].status=='ACTIVE'
    assert effective.milestones[-1].status=='PENDING'
    assert s.restore_checkpoint('S1')['contract_version']==2

@pytest.mark.parametrize('patch',[
    {'project_id':'other'}, {'session_id':'other'}, {'contract_version':2},
    {'milestone_id':'M2'}, {'topic':'SECURITY'},
    {'findings':[{'fact_id':'F1','provider':'GCP','reference_id':'UNKNOWN','summary':'invented'}]},
])
def test_invalid_handoffs_block(setup,patch):
    s,c,refs=setup
    assert validate_handoff(handoff(c,refs,**patch),c,'S1',refs).decision=='BLOCK'

def test_uncertain_research_stops_before_report(setup):
    s,c,refs=setup
    h=handoff(c,refs,unresolved_questions=['Evidence unclear'])
    client=ScriptedClient(h)
    result=run_specialist_step(s,client,c.project_id,'S1',refs,'A1')
    assert result.state=='AWAITING_REVIEW' and result.step is None
    assert client.count==1 and s.sections(c.project_id)=={}

def test_restart_between_research_and_report_reuses_handoff(setup):
    s,c,refs=setup
    client=ScriptedClient(handoff(c,refs),RuntimeError('interrupted report generation'))
    with pytest.raises(RuntimeError): run_specialist_step(s,client,c.project_id,'S1',refs,'A1')
    checkpoint=s.restore_checkpoint('S1')
    assert checkpoint['state']=='HANDOFF' and checkpoint['pending_action_id']=='A1'
    path=s.db.execute('PRAGMA database_list').fetchone()[2]
    reopened=Store(path)
    try:
        report=ScriptedClient(action(c,refs))
        result=run_specialist_step(reopened,report,c.project_id,'S1',refs,'A1')
        assert result.step.committed and result.handoff.replayed
        assert report.count==1
        replay=run_specialist_step(reopened,ScriptedClient(),c.project_id,'S1',refs,'A1')
        assert replay.step.replayed
        assert len([e for e in reopened.timeline(c.project_id) if e['kind']=='ACTION_COMMITTED'])==1
    finally: reopened.close()

def test_goal_change_invalidates_pending_handoff(setup):
    s,c,refs=setup
    s.save_handoff(handoff(c,refs),refs,action_id='A1')
    s.propose_goal_change(change(c))
    s.decide_goal_change('C-1',approve=True,actor='user')
    client=ScriptedClient()
    result=run_specialist_step(s,client,c.project_id,'S1',refs,'A1')
    assert result.state=='BLOCKED' and client.count==0
    assert s.restore_checkpoint('S1')['state']=='BLOCKED'
    assert s.sections(c.project_id)=={}

def test_report_cannot_use_sources_outside_handoff(setup):
    s,c,refs=setup
    report=action(c,refs)
    data=report.model_dump(mode='json')
    data['declared_effects']['reference_ids_used'].append(refs[3].reference_id)
    result=run_specialist_step(s,ScriptedClient(handoff(c,refs),AgentAction.model_validate(data)),
                               c.project_id,'S1',refs,'A1')
    assert result.state=='BLOCKED' and not result.step.committed

def test_four_session_state_survives_restart(setup):
    s,c,refs=setup
    assert run_specialist_step(s,ScriptedClient(handoff(c,refs),action(c,refs)),c.project_id,'S1',refs,'A1').step.committed
    s.start_session(c.project_id,'S2')
    bad=AgentAction.model_validate({**action(c,refs,'DRIFT','S2').model_dump(mode='json'),'topic':'SECURITY'})
    assert s.commit_action(bad,refs).validation.decision=='BLOCK'
    s.start_session(c.project_id,'S3')
    s.propose_goal_change(change(c))
    s.decide_goal_change('C-1',approve=True,actor='user')
    s.start_session(c.project_id,'S4')
    path=s.db.execute('PRAGMA database_list').fetchone()[2]
    reopened=Store(path)
    try:
        state=reopened.restore_checkpoint('S1')
        assert state['contract_version']==2
        assert 'cost' in state['artifacts']
        replay=run_specialist_step(reopened,ScriptedClient(),c.project_id,'S1',refs,'A1')
        assert replay.step.replayed and replay.step.action.contract_version==1
        assert reopened.current_contract(c.project_id).version==2
    finally: reopened.close()

def test_session_can_restore_before_first_inference(setup):
    s,c,refs=setup
    state=s.restore_checkpoint('S1')
    assert state['state']=='IDLE'
    assert state['contract_version']==1
    assert state['artifacts']=={} and state['handoffs']==[]

def test_change_key_cannot_be_reused(setup):
    s,c,refs=setup
    s.propose_goal_change(change(c))
    modified=GoalChange.model_validate({**change(c).model_dump(mode='json'),'rationale':'Different request'})
    with pytest.raises(ValueError,match='key reused'):
        s.propose_goal_change(modified)

def test_duplicate_finding_ids_require_block(setup):
    s,c,refs=setup
    h=handoff(c,refs)
    h=AgentHandoff.model_validate({**h.model_dump(mode='json'),'findings':[h.findings[0],h.findings[0]]})
    assert validate_handoff(h,c,'S1',refs).decision=='BLOCK'

def test_aggregate_handoff_cannot_leak_unapproved_serverless(setup):
    s,c,refs=setup
    data=c.model_dump(mode='json')
    for milestone in data['milestones']:
        milestone['status']='ACTIVE' if milestone['id']=='M3' else 'COMPLETED'
    from engine.schemas import GoalContract
    aggregate=GoalContract.model_validate(data)
    r=next(r for r in refs if r.topic=='SERVERLESS')
    h=handoff(c,refs,milestone_id='M3',topic='COMPARISON',findings=[{
        'fact_id':'F1','provider':r.provider,'reference_id':r.reference_id,'summary':r.summary}])
    assert validate_handoff(h,aggregate,'S1',refs).decision=='BLOCK'
