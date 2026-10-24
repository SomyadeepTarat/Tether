"""Credential loading and diagnostics, without actual credentials or network calls."""
from types import SimpleNamespace
import pytest
from backend.config import load_backend_environment
from backend.inference import configuration, inference_failure_message
from engine.llm_client import InferenceError


@pytest.fixture
def clean_key(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', '')
    monkeypatch.delenv('GROQ_API_KEY', raising=False)


def test_root_dotenv_loads_backend_key(tmp_path, clean_key):
    (tmp_path / '.env').write_text('GROQ_API_KEY=test-only-value\n', encoding='utf-8')
    load_backend_environment(tmp_path)
    import os
    assert os.environ['GROQ_API_KEY'] == 'test-only-value'
    assert configuration()['groq_key_configured'] is True
    assert 'test-only-value' not in str(configuration())


def test_shell_configuration_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'shell-test-value')
    (tmp_path / '.env').write_text('GROQ_API_KEY=file-test-value\n', encoding='utf-8')
    load_backend_environment(tmp_path)
    import os
    assert os.environ['GROQ_API_KEY'] == 'shell-test-value'


def test_backend_specific_file_precedes_root(tmp_path, clean_key):
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend/.env').write_text('GROQ_API_KEY=backend-test-value\n', encoding='utf-8')
    (tmp_path / '.env').write_text('GROQ_API_KEY=root-test-value\n', encoding='utf-8')
    load_backend_environment(tmp_path)
    import os
    assert os.environ['GROQ_API_KEY'] == 'backend-test-value'


def test_dotenv_does_not_expand_environment_references(tmp_path, clean_key):
    (tmp_path / '.env').write_text('GROQ_API_KEY="literal-${UNDEFINED}"\n', encoding='utf-8')
    load_backend_environment(tmp_path)
    import os
    assert os.environ['GROQ_API_KEY'] == 'literal-${UNDEFINED}'


def test_missing_key_and_backup_failure_are_explained():
    client = SimpleNamespace(calls=[{'provider':'groq','error_kind':'missing_credentials'}])
    message = inference_failure_message(InferenceError('ollama','connection_or_timeout'),client)
    assert 'key is missing' in message and 'restart FastAPI' in message


def test_auth_error_is_sanitized():
    error = InferenceError('groq','http_401')
    error.raw_response = 'private-test-value'
    message = inference_failure_message(error)
    assert 'rejected the API key' in message
    assert 'private-test-value' not in message

@pytest.mark.parametrize('kind,expected',[
    ('connection_or_timeout','Local Ollama is unavailable'),
    ('http_404','could not find the configured model'),
    ('structured_output_failed_twice','local model returned invalid'),
    ('http_500','Local Ollama inference failed'),
])
def test_local_errors_are_not_misreported_as_groq(kind,expected):
    message=inference_failure_message(InferenceError('ollama',kind))
    assert expected in message
    assert 'Groq model' not in message
    assert 'same saved action key' in message

@pytest.mark.parametrize('kind,expected',[
    ('http_429','Groq rate limit reached'),
    ('http_401','Groq rejected the API key'),
    ('http_403','Groq denied account'),
    ('structured_output_failed_twice','Groq returned invalid structured'),
])
def test_primary_failure_survives_backup_failure(kind,expected):
    client=SimpleNamespace(calls=[{'provider':'groq','error_kind':kind},
                                 {'provider':'ollama','error_kind':'connection_or_timeout'}])
    message=inference_failure_message(InferenceError('ollama','connection_or_timeout'),client)
    assert expected in message
    assert 'backup also failed' in message
    assert 'Local Ollama' in message
