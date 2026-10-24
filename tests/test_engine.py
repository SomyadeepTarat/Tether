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
    def respond(request,timeout):
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
