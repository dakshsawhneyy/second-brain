"""LLM providers, JSON-validated completion, and the sensitivity-aware router."""

from __future__ import annotations

import time

import json
from collections.abc import Mapping
from typing import Literal, Protocol, TypeVar
from urllib.parse import urlparse

from . import usage
import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

TASKS = ("triage", "extract", "synthesis")
DEFAULT_OLLAMA_URL = "http://localhost:11434"
CLOUD_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}


class ProviderError(Exception):
    """A provider call failed. Messages never contain API keys."""


class LLMOutputError(Exception):
    """The model's reply could not be turned into the requested structure."""


class SensitivityError(Exception):
    """Private data was about to be sent to a non-local provider."""


class ConfigError(Exception):
    """Routing or provider configuration is missing or invalid."""


class Provider(Protocol):
    name: str
    is_local: bool

    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


def _post(client: httpx.Client, name: str, url: str, body: dict, headers: dict | None = None) -> dict:
    try:
        resp = client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"{name}: HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise ProviderError(f"{name}: {type(e).__name__}") from None
    except ValueError:
        raise ProviderError(f"{name}: response was not JSON") from None
    if not isinstance(data, dict):
        raise ProviderError(f"{name}: unexpected response shape")
    return data


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OllamaProvider:
    def __init__(self, model: str, base_url: str = DEFAULT_OLLAMA_URL, client: httpx.Client | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"ollama:{model}"
        # Only a loopback host keeps data on this machine; a remote Ollama counts as non-local.
        # Ollama "cloud" models (name ends in -cloud or has a :cloud tag) are forwarded by the local
        # daemon to ollama.com, so they are non-local too, even on localhost.
        lowered = model.lower()
        runs_in_cloud = lowered.endswith("-cloud") or ":cloud" in lowered
        self.is_local = (urlparse(self.base_url).hostname or "") in _LOOPBACK_HOSTS and not runs_in_cloud
        self._client = client or httpx.Client(timeout=120)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        body: dict = {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0}}
        if system:
            body["system"] = system
        started = time.monotonic()
        try:
            data = _post(self._client, self.name, f"{self.base_url}/api/generate", body)
        except Exception as e:
            usage.log_call(provider="ollama", model=self.model, ok=False, started=started,
                           prompt_chars=len(prompt) + len(system or ""), error=type(e).__name__)
            raise
        text = data.get("response")
        ok = isinstance(text, str)
        usage.log_call(provider="ollama", model=self.model, ok=ok, started=started,
                       prompt_chars=len(prompt) + len(system or ""), out_chars=len(text) if ok else 0,
                       input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"))
        if not ok:
            raise ProviderError(f"{self.name}: malformed response")
        return text

    def __repr__(self) -> str:
        return f"OllamaProvider(model={self.model!r}, base_url={self.base_url!r})"


class OpenAICompatProvider:
    is_local = False

    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"openai-compat:{model}"
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=60)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": self.model, "messages": messages, "temperature": 0}
        data = _post(self._client, self.name, f"{self.base_url}/chat/completions", body,
                     headers={"Authorization": f"Bearer {self._api_key}"})
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name}: malformed response") from None
        if not isinstance(text, str):
            raise ProviderError(f"{self.name}: malformed response")
        return text

    def __repr__(self) -> str:
        return f"OpenAICompatProvider(model={self.model!r}, base_url={self.base_url!r})"


def _extract_json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        idx = text.find("{", idx + 1)
    raise ValueError("no JSON object found in reply")


def complete_json(provider: Provider, prompt: str, model_cls: type[T], retries: int = 1,
                  system: str | None = None) -> T:
    """Ask for JSON, validate it against model_cls; retry with the error, then raise LLMOutputError."""
    current = prompt
    last_error = "unknown"
    for _ in range(retries + 1):
        raw = provider.complete(current, system=system)
        try:
            return model_cls.model_validate(_extract_json_object(raw))
        except (ValueError, ValidationError) as e:
            last_error = str(e)[:500]
            current = (f"{prompt}\n\nYour previous reply was invalid ({last_error}). "
                       "Reply with ONLY one valid JSON object, nothing else.")
    raise LLMOutputError(f"{provider.name}: could not get valid JSON ({last_error})")


class Router:
    def __init__(self, routes: Mapping[str, Provider]):
        self._routes = dict(routes)

    def route(self, task: str, sensitivity: Literal["public", "private"] = "private") -> Provider:
        provider = self._routes[task]  # KeyError for unknown tasks
        if sensitivity != "public" and not provider.is_local:
            raise SensitivityError(f"{task}: private data must not go to non-local provider {provider.name}")
        return provider


def _build_provider(kind: str, env: Mapping[str, str]) -> Provider:
    if kind == "ollama":
        model = env.get("SB_OLLAMA_MODEL", "").strip()
        if not model:
            raise ConfigError("SB_OLLAMA_MODEL is not set")
        return OllamaProvider(model=model, base_url=env.get("SB_OLLAMA_URL", "").strip() or DEFAULT_OLLAMA_URL)
    if kind in CLOUD_BASE_URLS:
        prefix = f"SB_{kind.upper()}"
        key = env.get(f"{prefix}_API_KEY", "").strip()
        model = env.get(f"{prefix}_MODEL", "").strip()
        missing = [n for n, v in ((f"{prefix}_API_KEY", key), (f"{prefix}_MODEL", model)) if not v]
        if missing:
            raise ConfigError(f"missing settings for route '{kind}': {', '.join(missing)}")
        return OpenAICompatProvider(base_url=CLOUD_BASE_URLS[kind], api_key=key, model=model)
    raise ConfigError(f"unknown provider route: {kind!r}")


def build_router(env: Mapping[str, str]) -> Router:
    routes = {task: _build_provider(env.get(f"SB_ROUTE_{task.upper()}", "").strip().lower() or "ollama", env)
              for task in TASKS}
    return Router(routes)
