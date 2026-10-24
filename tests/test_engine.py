import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from engine.executor import Store
from engine.llm_client import OllamaClient
from engine.orchestrator import run_step
from engine.schemas import AgentAction, GoalContract, Reference
from engine.validator import validate_action

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def contract():
    return GoalContract.model_validate_json((ROOT / 'scenarios/cloud_comparison.json').read_text())

@pytest.fixture
def refs():
    return [Reference.model_validate(r) for r in json.loads((ROOT / 'scenarios/cloud_snapshot.json').read_text())['references']]

@pytest.fixture
def action(contract, refs):
    ref = refs[0]
    return AgentAction.model_validate({
        'action_id':'A-1','project_id':contract.project_id,'session_id':'S-1',
        'contract_version':1,'milestone_id':'M1','topic':'COST',
        'declared_effects':{'sections_created':['cost'],'sections_modified':[],
          'topics_introduced':['COST'],'reference_ids_used':[ref.reference_id],
          'numerical_claims':[{'value':'30','reference_id':ref.reference_id,'quote':ref.summary}]},
        'arguments':{'section_id':'cost','content':f'SYNTHETIC_DEMONSTRATION\n{ref.summary} [{ref.reference_id}]'},
        'rationale':'Research cost evidence'})

def change(action, **updates):
    return AgentAction.model_validate({**action.model_dump(mode='json'), **updates})

def test_supported_action(action, contract, refs):
    assert validate_action(action,contract,'S-1',refs).decision == 'ALLOW'

@pytest.mark.parametrize('updates', [
    {'project_id':'other'}, {'session_id':'other'}, {'contract_version':2},
    {'milestone_id':'missing'}, {'milestone_id':'M2'}, {'topic':'SECURITY'}])
def test_authority_blocks(action, contract, refs, updates):
    assert validate_action(change(action,**updates),contract,'S-1',refs).decision == 'BLOCK'

def test_source_and_effect_checks(action, contract, refs):
    for patch in [{'reference_ids_used':['UNKNOWN']}, {'sections_created':['wrong']},
                  {'topics_introduced':['DEPLOYMENT']}, {'numerical_claims':[]}]:
        effects = {**action.declared_effects.model_dump(mode='json'), **patch}
        assert validate_action(change(action,declared_effects=effects),contract,'S-1',refs).decision == 'BLOCK'

def test_undeclared_numbers(action, contract, refs):
    args = {**action.arguments.model_dump(), 'content':action.arguments.content + ' Extra 999 USD.'}
    assert validate_action(change(action,arguments=args),contract,'S-1',refs).decision == 'BLOCK'

def test_hidden_scope(action, contract, refs):
    args = {**action.arguments.model_dump(), 'content':action.arguments.content + ' Require enterprise compliance.'}
    assert validate_action(change(action,arguments=args),contract,'S-1',refs).decision == 'BLOCK'

def test_paraphrase_is_review(action, contract, refs):
    args = {**action.arguments.model_dump(), 'content':action.arguments.content + ' AWS is always the best choice.'}
    assert validate_action(change(action,arguments=args),contract,'S-1',refs).decision == 'REVIEW'

def test_schema_rejects_unknown(action):
    with pytest.raises(ValidationError):
        change(action, execute_without_validation=True)

def test_bad_contract_ids(contract):
    data=contract.model_dump(mode='json')
    data['milestones'].append(data['milestones'][0])
    with pytest.raises(ValidationError):
        GoalContract.model_validate(data)

def test_recovery_and_idempotency(tmp_path, action, contract, refs):
    path=tmp_path/'state.sqlite3'
    store=Store(path)
    store.create_goal_contract(contract)
    store.start_session(contract.project_id,'S-1')
    assert store.commit_action(action,refs).committed
    store.close()
    store=Store(path)
    assert store.restore_checkpoint('S-1')['artifacts']['cost'] == action.arguments.content
    assert store.commit_action(action,refs).replayed
    assert len(store.timeline(contract.project_id)) == 3
    with pytest.raises(ValueError, match='Idempotency'):
        store.commit_action(change(action,rationale='different'),refs)
    store.close()

def test_block_and_review_never_commit(tmp_path, action, contract, refs):
    store=Store(tmp_path/'test.db')
    store.create_goal_contract(contract)
    store.start_session(contract.project_id,'S-1')
    assert not store.commit_action(change(action,topic='SECURITY'),refs).committed
    reviewed=change(action,action_id='A-2',arguments={'section_id':'cost','content':action.arguments.content+' Best provider.'})
    assert store.commit_action(reviewed,refs).validation.decision == 'REVIEW'
    assert store.sections(contract.project_id) == {}
    store.close()

def test_orchestrator_replay_skips_model(tmp_path, action, contract, refs):
    class Client:
        def generate(self,*args):
            return action
    class NoModel:
        def generate(self,*args):
            raise AssertionError('Replay must not call inference')
    store=Store(tmp_path/'test.db')
    store.create_goal_contract(contract)
    store.start_session(contract.project_id,'S-1')
    assert run_step(store,Client(),contract.project_id,'S-1',refs,'A-1').committed
    assert run_step(store,NoModel(),contract.project_id,'S-1',refs,'A-1').replayed
    store.close()

def test_local_only_adapter():
    with pytest.raises(ValueError):
        OllamaClient(base_url='https://example.com')

def test_adapter_bounded_json_retry(monkeypatch):
    import io
    import engine.llm_client as adapter
    from engine.schemas import ValidationResult
    replies=iter(['{}', '{"decision":"ALLOW","reasons":[]}'])
    def fake_open(*args,**kwargs):
        return io.BytesIO(json.dumps({'message':{'content':next(replies)}}).encode())
    monkeypatch.setattr(adapter,'urlopen',fake_open)
    client=OllamaClient()
    assert client.generate(ValidationResult,'system','prompt').decision == 'ALLOW'
    assert [c['schema_valid'] for c in client.calls] == [False,True]

def test_adapter_exhausted_json_retry(monkeypatch):
    import io
    import engine.llm_client as adapter
    from engine.schemas import ValidationResult
    monkeypatch.setattr(adapter,'urlopen',lambda *a,**k:io.BytesIO(b'{"message":{"content":"{}"}}'))
    client=OllamaClient()
    with pytest.raises(ValueError,match='twice'):
        client.generate(ValidationResult,'system','prompt')
    assert len(client.calls)==2

def test_initial_contract_cannot_be_replaced(tmp_path, contract):
    store=Store(tmp_path/'test.db')
    store.create_goal_contract(contract)
    with pytest.raises(ValueError,match='already exists'):
        store.create_goal_contract(contract.model_copy(update={'objective':'Unauthorized change'}))
    assert store.current_contract(contract.project_id).objective==contract.objective
    assert len(store.timeline(contract.project_id))==1
    store.close()

def test_primary_block_does_not_trigger_fallback_and_attribution_survives_restart(tmp_path, action, contract, refs, monkeypatch):
    import io
    import engine.llm_client as adapter
    from engine.llm_client import FallbackClient, GroqClient, OllamaClient
    blocked = change(action, topic='SECURITY').model_dump(mode='json')
    requests=[]
    def respond(request,timeout,**kwargs):
        requests.append(request.full_url)
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(blocked)},
                                                  'finish_reason':'stop'}]}).encode())
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=FallbackClient(GroqClient(api_key='test-secret'),OllamaClient())
    path=tmp_path/'test.db'
    store=Store(path)
    store.create_goal_contract(contract)
    store.start_session(contract.project_id,'S-1')
    result=run_step(store,c,contract.project_id,'S-1',refs,'A-1')
    assert result.validation.decision=='BLOCK'
    assert not result.committed and not store.sections(contract.project_id)
    assert len(requests)==1 and not c.backup.calls
    store.close()
    store=Store(path)
    attribution=next(e['body'] for e in store.timeline(contract.project_id)
                     if e['kind']=='INFERENCE_COMPLETED')
    assert attribution['attempts'][0]['provider']=='groq'
    assert 'test-secret' not in json.dumps(attribution)
    assert run_step(store,c,contract.project_id,'S-1',refs,'A-1').replayed
    assert len(requests)==1
    store.close()

def test_human_review_commits_without_rewriting_gateway_decision(tmp_path, action, contract, refs):
    store=Store(tmp_path/'review.db')
    store.create_goal_contract(contract);store.start_session(contract.project_id,'S-1')
    reviewed=change(action,arguments={'section_id':'cost','content':action.arguments.content+' Suitable for this workload.'})
    assert store.commit_action(reviewed,refs).validation.decision=='REVIEW'
    store.resolve_action(action.action_id,refs,approve=True,actor='user',reason='Compared every claim against the supplied evidence.')
    assert store.action_result(action.action_id).committed
    assert store.action_result(action.action_id).validation.decision=='REVIEW'
    before=len(store.timeline(contract.project_id))
    store.resolve_action(action.action_id,refs,approve=True,actor='user',reason='Evidence was checked again.')
    assert len(store.timeline(contract.project_id))==before
    with pytest.raises(ValueError,match='final'):
        store.resolve_action(action.action_id,refs,approve=False,actor='user')
    store.close()

def test_block_cannot_be_human_overridden(tmp_path, action, contract, refs):
    store=Store(tmp_path/'review.db');store.create_goal_contract(contract);store.start_session(contract.project_id,'S-1')
    store.commit_action(change(action,topic='SECURITY'),refs)
    with pytest.raises(ValueError,match='Only uncommitted REVIEW'):
        store.resolve_action(action.action_id,refs,approve=True,actor='user',reason='Attempted policy override.')
    assert store.sections(contract.project_id)=={}
    store.close()

def test_review_requires_actor_explanation_and_unchanged_artifact(tmp_path, action, contract, refs):
    store=Store(tmp_path/'review.db');store.create_goal_contract(contract);store.start_session(contract.project_id,'S-1')
    reviewed=change(action,arguments={'section_id':'cost','content':action.arguments.content+' Reasonable option.'})
    store.commit_action(reviewed,refs)
    with pytest.raises(ValueError,match='actor'):
        store.resolve_action(action.action_id,refs,approve=True,actor='',reason='Checked evidence carefully.')
    with pytest.raises(ValueError,match='Explain'):
        store.resolve_action(action.action_id,refs,approve=True,actor='user')
    store.commit_action(change(action,action_id='A-NEW'),refs)
    with pytest.raises(ValueError):
        store.resolve_action(action.action_id,refs,approve=True,actor='user',reason='Checked evidence carefully.')
    assert not store.action_result(action.action_id).committed
    store.close()

def test_nested_transaction_rollback_is_atomic(tmp_path, contract):
    store=Store(tmp_path/'nested.db')
    with pytest.raises(RuntimeError):
        with store._transaction():
            store.create_goal_contract(contract)
            raise RuntimeError('Abort outer operation')
    with pytest.raises(ValueError,match='Unknown project'): store.current_contract(contract.project_id)
    assert store.timeline(contract.project_id)==[]
    store.close()

def test_review_rechecks_base_when_an_existing_section_changes(tmp_path, action, contract, refs):
    store=Store(tmp_path/'review.db');store.create_goal_contract(contract);store.start_session(contract.project_id,'S-1')
    store.commit_action(action,refs)
    effects={**action.declared_effects.model_dump(mode='json'),'sections_created':[],'sections_modified':['cost']}
    pending=change(action,action_id='A-PENDING',declared_effects=effects,
        arguments={'section_id':'cost','content':action.arguments.content+' Supported recommendation.'})
    assert store.commit_action(pending,refs).validation.decision=='REVIEW'
    store.commit_action(change(action,action_id='A-NEWER',declared_effects=effects),refs)
    with pytest.raises(ValueError,match='Report changed'):
        store.resolve_action('A-PENDING',refs,approve=True,actor='user',reason='Checked every source and claim.')
    assert not store.action_result('A-PENDING').committed
    store.close()


def test_independent_grader_detects_scope_sources_and_version(action,contract,refs):
    from engine.evaluator import grade_action
    assert grade_action(action,contract,refs)['source_fidelity']=='SUPPORTED'
    data=change(action,contract_version=2,topic='SECURITY')
    grade=grade_action(data,contract,refs)
    assert not grade['authorized']
    assert {'goal_version','topic_authorization'}<=set(grade['violations'])
    unsupported=change(action,arguments={'section_id':'cost','content':action.arguments.content+' Cost 999 USD.'})
    assert grade_action(unsupported,contract,refs)['source_fidelity']=='UNSUPPORTED'
    prose=change(action,arguments={'section_id':'cost','content':action.arguments.content+' Best option.'})
    assert grade_action(prose,contract,refs)['source_fidelity']=='UNVERIFIED'


def test_evaluation_modes_use_same_prompt_and_never_write_reports(action,contract,refs):
    from engine.evaluator import evaluate_run
    prompts=[]
    class Client:
        provider='test-double';model='scripted';calls=[]
        def generate(self,schema,system,prompt):
            prompts.append((system,prompt))
            data=json.loads(prompt)
            return change(action,action_id=data['action_id'],session_id=data['session_id'],topic='SECURITY')
    baseline=evaluate_run(Client(),contract,refs,mode='baseline')
    tether=evaluate_run(Client(),contract,refs,mode='tether')
    assert prompts[0]==prompts[1]
    assert baseline['committed'] and not tether['committed']
    assert baseline['metrics']['unauthorized_action_rate']==1
    assert tether['metrics']['unauthorized_action_rate'] is None
    assert tether['decision']=='BLOCK'

def test_independent_grader_checks_declared_effects_and_numerical_evidence(action,contract,refs):
    from engine.evaluator import grade_action
    effects={**action.declared_effects.model_dump(mode='json'),'sections_created':[],'numerical_claims':[]}
    grade=grade_action(change(action,declared_effects=effects),contract,refs)
    assert not grade['authorized']
    assert {'section_effects','undeclared_number'}<=set(grade['violations'])

def test_cost_placeholder_cannot_be_committed_through_review(action,contract,refs):
    effects={**action.declared_effects.model_dump(mode='json'),'numerical_claims':[]}
    placeholder=change(action,declared_effects=effects,
        arguments={'section_id':'cost','content':'SYNTHETIC_DEMONSTRATION AWS: [SNAPSHOT-AWS-COST]'})
    assert validate_action(placeholder,contract,'S-1',refs).decision=='BLOCK'

def test_report_feedback_does_not_reintroduce_historical_identity(action,contract,refs):
    from engine.report_agent import plan_next_action
    old=change(action,action_id='OLD-APPLICATION-IDENTITY')
    feedback={'action':old.model_dump(mode='json'),'validation':{'decision':'BLOCK','reasons':['Identity mismatch']}}
    class Client:
        def generate(self,schema,system,prompt):
            data=json.loads(prompt)
            assert 'OLD-APPLICATION-IDENTITY' not in prompt
            assert data['action_id']==action.action_id
            assert data['project_id']==contract.project_id
            assert data['previous_attempt_feedback']['validation']['decision']=='BLOCK'
            return action
    assert plan_next_action(Client(),contract,'S-1',refs,action.action_id,previous_feedback=feedback)==action
