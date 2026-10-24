"""Provider routing is tested without real credentials or paid requests."""
import io
import json
from urllib.error import HTTPError, URLError

import pytest
import engine.llm_client as adapter
from engine.llm_client import (GroqClient, OllamaClient, FallbackClient, InferenceError,
                               create_inference_client, strict_json_schema)
from engine.schemas import AgentAction, ValidationResult

ANSWER = '{"decision":"ALLOW","reasons":[]}'

def groq_response(content=ANSWER, **choice_fields):
    return io.BytesIO(json.dumps({'choices':[{'message':{'content':content},
                                             'finish_reason':'stop', **choice_fields}]}).encode())

def ollama_response():
    return io.BytesIO(json.dumps({'message':{'content':ANSWER}}).encode())

def client():
    return FallbackClient(GroqClient(api_key='test-secret'), OllamaClient())

def test_groq_success_and_secret_not_logged(monkeypatch):
    def respond(request,timeout,**kwargs):
        payload=json.loads(request.data)
        assert request.get_header('Authorization') == 'Bearer test-secret'
        assert request.get_header('User-agent') == 'Tether/0.2'
        import ssl
        assert kwargs['context'].verify_mode == ssl.CERT_REQUIRED
        assert kwargs['context'].check_hostname
        assert payload['model']=='openai/gpt-oss-20b'
        assert payload['reasoning_effort']=='low'
        assert payload['response_format']['json_schema']['strict'] is True
        assert timeout == 15
        return groq_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=client()
    assert c.generate(ValidationResult,'system','prompt').decision == 'ALLOW'
    assert len(c.calls)==1
    assert c.calls[0]['provider']=='groq'
    assert not c.backup.calls
    assert 'test-secret' not in json.dumps(c.calls)

def test_strict_schema_handles_nested_defaults_without_mutation():
    original=AgentAction.model_json_schema()
    result=strict_json_schema(AgentAction)
    def check(node):
        if isinstance(node,dict):
            assert 'default' not in node
            if node.get('type')=='object':
                assert set(node['required'])==set(node['properties'])
                assert node['additionalProperties'] is False
            for value in node.values(): check(value)
        elif isinstance(node,list):
            for value in node: check(value)
    check(result)
    assert AgentAction.model_json_schema()==original

@pytest.mark.parametrize('status',[401,403,408,429,498,500,503])
def test_http_failure_falls_back_once(monkeypatch,status):
    requests=[]
    def respond(request,timeout,**kwargs):
        requests.append(request.full_url)
        if 'api.groq.com' in request.full_url:
            raise HTTPError(request.full_url,status,'secret error body',{},io.BytesIO())
        return ollama_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=client()
    assert c.generate(ValidationResult,'system','prompt').decision=='ALLOW'
    assert len(requests)==2
    assert c.calls[-1]['fallback_reason']==f'http_{status}'
    assert c.calls[-1]['provider']=='ollama'
    assert 'secret error body' not in json.dumps(c.calls)

@pytest.mark.parametrize('error',[URLError('network unavailable'),TimeoutError()])
def test_network_failure_falls_back(monkeypatch,error):
    def respond(request,timeout,**kwargs):
        if 'api.groq.com' in request.full_url:
            raise error
        return ollama_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=client()
    c.generate(ValidationResult,'s','p')
    assert c.calls[-1]['fallback_reason']=='connection_or_timeout'

def test_missing_key_skips_remote_request(monkeypatch):
    requests=[]
    def respond(request,timeout,**kwargs):
        requests.append(request.full_url)
        return ollama_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=FallbackClient(GroqClient(api_key=''),OllamaClient())
    c.generate(ValidationResult,'s','p')
    assert len(requests)==1 and '127.0.0.1' in requests[0]
    assert c.calls[0]['error_kind']=='missing_credentials'
    assert c.calls[-1]['fallback_reason']=='missing_credentials'

def test_invalid_groq_output_retries_then_falls_back(monkeypatch):
    def respond(request,timeout,**kwargs):
        return groq_response('{}') if 'api.groq.com' in request.full_url else ollama_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=client()
    c.generate(ValidationResult,'s','p')
    assert len(c.calls)==3
    assert c.calls[-1]['fallback_reason']=='structured_output_failed_twice'

@pytest.mark.parametrize('status',[400,404,422])
def test_bad_request_does_not_hide_configuration_error(monkeypatch,status):
    def respond(request,timeout,**kwargs):
        raise HTTPError(request.full_url,status,'bad configuration',{},io.BytesIO())
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=client()
    with pytest.raises(InferenceError): c.generate(ValidationResult,'s','p')
    assert not c.backup.calls

def test_provider_refusal_does_not_trigger_backup(monkeypatch):
    monkeypatch.setattr(adapter,'urlopen',lambda *a,**k:groq_response(finish_reason='content_filter'))
    c=client()
    with pytest.raises(InferenceError,match='provider_refusal'):
        c.generate(ValidationResult,'s','p')
    assert not c.backup.calls

def test_both_providers_fail_without_fake_success(monkeypatch):
    def fail(*a,**k): raise URLError('offline')
    monkeypatch.setattr(adapter,'urlopen',fail)
    c=client()
    with pytest.raises(InferenceError): c.generate(ValidationResult,'s','p')
    assert len(c.calls)==2
    assert not any(call['schema_valid'] for call in c.calls)

def test_provider_selection(monkeypatch):
    monkeypatch.delenv('TETHER_PROVIDER',raising=False)
    assert isinstance(create_inference_client(),FallbackClient)
    assert isinstance(create_inference_client('groq-only'),GroqClient)
    assert isinstance(create_inference_client('ollama'),OllamaClient)
    with pytest.raises(ValueError): create_inference_client('other')


def test_env_file_load_does_not_override_explicit_process_settings(tmp_path,monkeypatch):
    from engine.config import load_environment
    path=tmp_path/'.env'
    path.write_text('TETHER_TEST_SETTING=from-file\nTETHER_ANOTHER_TEST=loaded\n')
    monkeypatch.setenv('TETHER_TEST_SETTING','explicit')
    monkeypatch.delenv('TETHER_ANOTHER_TEST',raising=False)
    try:
        load_environment(path)
        import os
        assert os.environ['TETHER_TEST_SETTING']=='explicit'
        assert os.environ['TETHER_ANOTHER_TEST']=='loaded'
    finally:
        import os
        os.environ.pop('TETHER_ANOTHER_TEST',None)

def test_groq_json_generation_failure_retries_without_hiding_bad_requests(monkeypatch):
    count=0
    def respond(request,timeout,**kwargs):
        nonlocal count
        count+=1
        if count==1:
            raise HTTPError(request.full_url,400,'Bad Request',{},io.BytesIO(
                b'{"error":{"code":"json_validate_failed","message":"Missing agent"}}'))
        return groq_response()
    monkeypatch.setattr(adapter,'urlopen',respond)
    c=GroqClient(api_key='test-only')
    assert c.generate(ValidationResult,'system','prompt').decision=='ALLOW'
    assert len(c.calls)==2 and c.calls[0]['error_kind']=='invalid_structured_output'
    assert c.calls[1]['schema_valid']


def test_literal_properties_have_single_option_enum_for_groq():
    schema=strict_json_schema(AgentAction)
    assert schema['properties']['agent']['enum']==['REPORT']
    assert schema['properties']['action_type']['enum']==['WRITE_SECTION']
    assert 'const' not in schema['properties']['agent']
