"""Backend provider factory and telemetry allowlist; inference stays in the engine."""
from dataclasses import asdict, is_dataclass
from importlib import import_module
import os
import re
from typing import Any


class EngineUnavailable(RuntimeError):
    pass


def configuration():
    from engine.config import load_environment
    load_environment()
    provider = os.environ.get('TETHER_PROVIDER', 'groq')
    return {
        'provider': provider,
        'model': os.environ.get('OLLAMA_MODEL', 'qwen3:4b') if provider == 'ollama' else os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'),
        'fallback_enabled': provider == 'groq',
        'hosted_inputs': provider in ('groq', 'groq-only'),
        'groq_key_configured': bool(os.environ.get('GROQ_API_KEY', '').strip()),
    }


def create_client(provider=None):
    if configuration()['provider'] not in ('groq', 'groq-only', 'ollama'):
        raise EngineUnavailable('Invalid TETHER_PROVIDER. Use groq, groq-only, or ollama.')
    try:
        module = import_module('engine.llm_client')
    except ModuleNotFoundError as exc:
        raise EngineUnavailable('AI engine integration pending. The engine/ package has not been supplied yet.') from exc
    return module.create_inference_client(provider=provider)


def inference_failure_message(exc, client=None):
    """Translate known error codes without exposing provider bodies or secrets."""
    calls = getattr(client, 'calls', [])
    if any(c.get('provider') == 'groq' and c.get('error_kind') == 'missing_credentials' for c in calls):
        return 'Groq API key is missing. Add GROQ_API_KEY to the backend .env file and restart FastAPI. The local backup did not produce a result.'
    kind = getattr(exc, 'kind', '')
    provider = getattr(exc, 'provider', '')
    if provider == 'ollama':
        local = {
            'connection_or_timeout': 'Local Ollama is unavailable or timed out. Start Ollama and install the configured model with ollama pull qwen3:4b.',
            'http_404': 'Ollama could not find the configured model. Run ollama pull qwen3:4b, or install the model named in OLLAMA_MODEL.',
            'structured_output_failed_twice': 'The local model returned invalid structured output twice. No proposal was committed.',
        }.get(kind, 'Local Ollama inference failed. Check the local server and configured model.')
        hosted_kind = next((c.get('error_kind') for c in reversed(calls)
                            if c.get('provider') == 'groq' and c.get('error_kind')), None)
        if hosted_kind:
            primary = {
                'http_429': 'Groq rate limit reached. Wait for your free-plan limit to reset before retrying.',
                'http_401': 'Groq rejected the API key.',
                'http_403': 'Groq denied account or model access.',
                'structured_output_failed_twice': 'Groq returned invalid structured output twice.',
                'connection_or_timeout': 'Groq could not be reached or timed out.',
                'tls_verification_failed': 'Groq TLS certificate verification failed. Check your system certificates or SSL_CERT_FILE configuration.',
            }.get(hosted_kind, 'The Groq request failed.')
            return primary + ' The local backup also failed. ' + local + ' Retry resumes the same saved action key.'
        return local + ' Retry resumes the same saved action key.'
    messages = {
        'missing_credentials': 'Groq API key is missing. Add GROQ_API_KEY to the backend .env file and restart FastAPI.',
        'http_401': 'Groq rejected the API key. Check the backend GROQ_API_KEY and restart FastAPI.',
        'http_403': 'Groq denied access. Check your account and model access.',
        'http_429': 'Groq rate limit reached. Check your free-plan limits; this step was not committed.',
        'http_400': 'Groq rejected the request format or model settings. Inspect the recorded attempt status.',
        'http_404': 'The configured Groq model or endpoint was not found.',
        'connection_or_timeout': 'The inference provider could not be reached. Check connectivity and provider availability.',
        'tls_verification_failed': 'Groq TLS certificate verification failed. Check your system certificates or SSL_CERT_FILE configuration; do not disable certificate verification.',
        'provider_refusal': 'The inference provider declined this request. No proposal was committed.',
        'structured_output_failed_twice': 'The model did not return valid structured output after two attempts. No proposal was committed.',
    }
    message = messages.get(kind, 'Engine execution failed. Check provider configuration and persisted inference attempts.')
    return message + ' Retry resumes the same saved action key.'


def public_attempts(calls: list[Any]) -> list[dict]:
    """Persist only the agreed telemetry fields, never raw prompts or credentials."""
    fields = {'provider', 'model', 'agent', 'started_at', 'attempt', 'schema_valid', 'elapsed_seconds', 'error_kind', 'http_status', 'fallback_from', 'fallback_reason'}
    attempts = []
    for call in calls:
        if hasattr(call, 'model_dump'):
            source = call.model_dump(mode='json')
        elif is_dataclass(call):
            source = asdict(call)
        elif isinstance(call, dict):
            source = call
        else:
            source = {name: getattr(call, name) for name in fields if hasattr(call, name)}
        result = {}
        for key in fields:
            value = source.get(key)
            if value is None:
                continue
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            if isinstance(value, str):
                secret = os.environ.get('GROQ_API_KEY')
                if secret:
                    value = value.replace(secret, '[redacted]')
                value = re.sub(r'gsk_[A-Za-z0-9_-]+', '[redacted]', value)[:400]
            if isinstance(value, (str, int, float, bool)):
                result[key] = value
        attempts.append(result)
    return attempts
