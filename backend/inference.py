"""Temporary interface to the incoming engine; no provider logic is duplicated here."""
from dataclasses import asdict, is_dataclass
from importlib import import_module
import os
import re
from typing import Any


class EngineUnavailable(RuntimeError):
    pass


def configuration():
    provider = os.environ.get('TETHER_PROVIDER', 'groq')
    return {
        'provider': provider,
        'model': os.environ.get('OLLAMA_MODEL', 'qwen3:4b') if provider == 'ollama' else os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b'),
        'fallback_enabled': provider == 'groq',
        'hosted_inputs': provider in ('groq', 'groq-only'),
    }


def create_client():
    if configuration()['provider'] not in ('groq', 'groq-only', 'ollama'):
        raise EngineUnavailable('Invalid TETHER_PROVIDER. Use groq, groq-only, or ollama.')
    try:
        module = import_module('engine.llm_client')
    except ModuleNotFoundError as exc:
        raise EngineUnavailable('AI engine integration pending. The engine/ package has not been supplied yet.') from exc
    return module.create_inference_client()


def public_attempts(calls: list[Any]) -> list[dict]:
    """Persist only the agreed telemetry fields, never raw prompts or credentials."""
    fields = {'provider', 'model', 'started_at', 'attempt', 'schema_valid', 'elapsed_seconds', 'error_kind', 'http_status', 'fallback_from', 'fallback_reason'}
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
