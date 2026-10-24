"""Structured inference: Groq primary, local Ollama backup, one authorization path."""
import json
import os
import time
import ssl
import threading
import certifi
from copy import deepcopy
from datetime import datetime, timezone
from typing import Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class InferenceClient(Protocol):
    provider: str
    calls: list[dict]
    model: str

    def generate(self, schema: type[T], system: str, prompt: str) -> T: ...


class InferenceError(ValueError):
    """Sanitized error; provider response bodies/credentials are never error text."""

    def __init__(self, provider, kind, *, fallback_allowed=True, retry_after=None):
        self.provider = provider
        self.kind = kind
        self.fallback_allowed = fallback_allowed
        self.retry_after = retry_after
        super().__init__(f"{provider}: {kind}")


def strict_json_schema(schema: type[BaseModel]) -> dict:
    """Groq requires every property to be required, including defaulted fields.

    This transport copy never changes the application/Pydantic schema.
    """
    result = deepcopy(schema.model_json_schema())

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


class _StructuredClient:
    def generate(self, schema: type[T], system: str, prompt: str) -> T:
        for attempt in range(2):
            payload = self._payload(schema, system, prompt)
            record = {"provider": self.provider, "model": self.model,
                      "started_at": datetime.now(timezone.utc).isoformat(),
                      "request": payload, "attempt": attempt + 1, "schema_valid": False}
            self.calls.append(record)
            start = time.perf_counter()
            try:
                if self.provider == "groq" and not self.api_key:
                    raise InferenceError(self.provider, "missing_credentials")
                headers = {"Content-Type": "application/json", "User-Agent": "Tether/0.2"}
                if self.provider == "groq":
                    headers["Authorization"] = f"Bearer {self.api_key}"
                request = Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers)
                transport = {}
                if self.provider == "groq":
                    # Keep platform trust (including Windows-managed roots) and
                    # supplement it with Mozilla roots. Passing certifi as cafile
                    # alone discards platform roots on Windows.
                    custom_ca = os.getenv("SSL_CERT_FILE")
                    context = ssl.create_default_context(cafile=custom_ca)
                    if not custom_ca:
                        context.load_verify_locations(cafile=certifi.where())
                    transport["context"] = context
                with urlopen(request, timeout=self.timeout, **transport) as response:
                    raw = json.load(response)
                record["response"] = raw
                content = self._content(raw)
                result = schema.model_validate_json(content)
                record["schema_valid"] = True
                return result
            except HTTPError as exc:
                # Only Groq may retry a bounded, server-specified rate-limit wait.
                # Malformed requests and policy decisions never trigger retries.
                record["http_status"] = exc.code
                generation_failure = False
                if self.provider == "groq" and exc.code == 400:
                    try:
                        body = json.loads(exc.read(65536))
                        generation_failure = body.get("error", {}).get("code") == "json_validate_failed"
                    except (ValueError, AttributeError, TypeError):
                        pass
                retry_after = None
                if self.provider == "groq" and exc.code == 429:
                    try:
                        retry_after = float(exc.headers.get('retry-after', ''))
                    except (ValueError, TypeError, AttributeError):
                        pass
                exc.close()
                if generation_failure:
                    record["error_kind"] = "invalid_structured_output"
                    if attempt:
                        raise InferenceError(self.provider, "structured_output_failed_twice") from None
                    prompt += "\nInclude ALL schema properties, including agent and action_type. Do not omit defaulted fields."
                    continue
                raise InferenceError(self.provider, f"http_{exc.code}",
                                     fallback_allowed=exc.code in {401, 403, 408, 429, 498} or exc.code >= 500, retry_after=retry_after) from None
            except (URLError, TimeoutError, OSError) as exc:
                if isinstance(exc, ssl.SSLCertVerificationError) or isinstance(getattr(exc, 'reason', None), ssl.SSLCertVerificationError):
                    record["error_kind"] = "tls_verification_failed"
                    raise InferenceError(self.provider, "tls_verification_failed") from None
                raise InferenceError(self.provider, "connection_or_timeout") from None
            except (ValidationError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                record["error_kind"] = "invalid_structured_output"
                if attempt:
                    raise InferenceError(self.provider, "structured_output_failed_twice") from None
                prompt += "\nReturn a complete object matching the supplied JSON schema."
            except InferenceError as exc:
                record["error_kind"] = exc.kind
                raise
            finally:
                record["elapsed_seconds"] = time.perf_counter() - start
                # HTTP/network exceptions are raised from sibling except blocks.
                if not record["schema_valid"] and "error_kind" not in record:
                    record["error_kind"] = (f"http_{record['http_status']}" if "http_status" in record
                                            else "connection_or_timeout")


class OllamaClient(_StructuredClient):
    provider = "ollama"

    def __init__(self, base_url=None, model=None, timeout=120):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama must use a local HTTP endpoint")
        self.endpoint = self.base_url + "/api/chat"
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.timeout = timeout
        self.calls = []

    def _payload(self, schema, system, prompt):
        return {"model": self.model, "stream": False, "think": False,
                "format": schema.model_json_schema(),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 1800}}

    def _content(self, raw):
        return raw["message"]["content"]


class GroqClient(_StructuredClient):
    provider = "groq"
    _request_lock = threading.RLock()
    _cooldowns = {}

    def __init__(self, api_key=None, model=None, timeout=15):
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        self.timeout = timeout
        self.calls = []

    def generate(self, schema: type[T], system: str, prompt: str) -> T:
        # Shared across clients/projects in the single API worker. A provider
        # cooldown must survive the short-lived client created for each step.
        with self._request_lock:
            key = (self.api_key, self.model)
            remaining = self._cooldowns.get(key, 0) - time.monotonic()
            if remaining > 0:
                self.calls.append({"provider":self.provider, "model":self.model,
                    "schema_valid":False, "error_kind":"http_429", "elapsed_seconds":0})
                raise InferenceError(self.provider, 'http_429', retry_after=remaining)
            try:
                return self._generate_with_retry(schema, system, prompt)
            except InferenceError as exc:
                if exc.kind == 'http_429':
                    self._cooldowns[key] = time.monotonic() + max(1, exc.retry_after if exc.retry_after is not None else 60)
                raise

    def _generate_with_retry(self, schema: type[T], system: str, prompt: str) -> T:
        try:
            return super().generate(schema, system, prompt)
        except InferenceError as exc:
            # One bounded retry honors Groq's Retry-After. Daily quotas or long
            # waits fail/fall back visibly, rather than hanging the workflow.
            delay = exc.retry_after
            if exc.kind != 'http_429' or delay is None or not 0 <= delay <= 45:
                raise
            callback = getattr(self, 'on_retry', None)
            if callback:
                callback(delay)
            time.sleep(delay)
            return super().generate(schema, system, prompt)

    def _payload(self, schema, system, prompt):
        payload = {"model": self.model, "stream": False, "temperature": 0,
                "max_completion_tokens": 1800,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "strict": True, "schema": strict_json_schema(schema)}}}
        if self.model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            payload["reasoning_effort"] = "low"
        return payload

    def _content(self, raw):
        choice = raw["choices"][0]
        if choice["message"].get("refusal") or choice.get("finish_reason") == "content_filter":
            raise InferenceError(self.provider, "provider_refusal", fallback_allowed=False)
        if choice.get("finish_reason") not in {None, "stop"}:
            raise KeyError("Incomplete model output")
        return choice["message"]["content"]


class FallbackClient:
    """Fail over inference only. Validation REVIEW/BLOCK never triggers failover."""
    provider = "groq_with_ollama_fallback"

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.model = primary.model
        self.calls = []

    def generate(self, schema: type[T], system: str, prompt: str) -> T:
        start = len(self.primary.calls)
        error = None
        try:
            return self.primary.generate(schema, system, prompt)
        except InferenceError as exc:
            if not exc.fallback_allowed:
                raise
            error = exc
        finally:
            self.calls.extend(self.primary.calls[start:])
        start = len(self.backup.calls)
        try:
            return self.backup.generate(schema, system, prompt)
        finally:
            for call in self.backup.calls[start:]:
                self.calls.append({**call, "fallback_from": self.primary.provider,
                                   "fallback_reason": error.kind})


def create_inference_client(provider=None) -> InferenceClient:
    """TETHER_PROVIDER=groq (default, with backup), groq-only, or ollama."""
    from engine.config import load_environment
    load_environment()
    selected = provider or os.getenv("TETHER_PROVIDER", "groq")
    if selected == "ollama":
        return OllamaClient()
    if selected == "groq-only":
        return GroqClient(timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "15")))
    if selected == "groq":
        return FallbackClient(GroqClient(timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "15"))), OllamaClient())
    raise ValueError("TETHER_PROVIDER must be groq, groq-only, or ollama")
