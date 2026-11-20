import json

import httpx
import pytest
from pydantic import BaseModel

from secondbrain.llm import (
    ConfigError,
    LLMOutputError,
    OllamaProvider,
    OpenAICompatProvider,
    ProviderError,
    Router,
    SensitivityError,
    build_router,
    complete_json,
)

SECRET = "sk-super-secret-key-123"


class Out(BaseModel):
    topic: str
    score: int


class FakeProvider:
    def __init__(self, replies, is_local=True, name="fake"):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []
        self.is_local = is_local
        self.name = name

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.replies.pop(0)


def client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_sends_prompt_and_returns_text():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"response": "pong"})

    p = OllamaProvider(model="qwen", client=client_with(handler))
    assert p.complete("ping", system="be brief") == "pong"
    assert seen["url"] == "http://localhost:11434/api/generate"
    assert seen["body"]["model"] == "qwen" and seen["body"]["prompt"] == "ping"
    assert seen["body"]["system"] == "be brief" and seen["body"]["stream"] is False
    assert p.is_local is True


@pytest.mark.parametrize("url,local", [
    ("http://localhost:11434", True),
    ("http://127.0.0.1:11434", True),
    ("http://[::1]:11434", True),
    ("http://192.168.1.50:11434", False),
    ("https://my-gpu-box.example.com", False),
    ("http://localhost.evil.com:11434", False),
])
def test_ollama_is_local_only_when_host_is_loopback(url, local):
    p = OllamaProvider(model="m", base_url=url, client=client_with(lambda r: httpx.Response(200, json={"response": ""})))
    assert p.is_local is local


@pytest.mark.parametrize("model,local", [
    ("qwen2.5:7b", True),
    ("llama3.1:8b-instruct-q4_K_M", True),
    ("gpt-oss:120b-cloud", False),
    ("qwen3-coder:480b-cloud", False),
    ("deepseek:cloud", False),
    ("SOME-MODEL-CLOUD", False),
])
def test_ollama_cloud_models_are_not_local_even_on_localhost(model, local):
    p = OllamaProvider(model=model, client=client_with(lambda r: httpx.Response(200, json={"response": ""})))
    assert p.is_local is local


def test_ollama_cloud_model_blocked_for_private_data():
    p = OllamaProvider(model="gpt-oss:120b-cloud", client=client_with(lambda r: httpx.Response(200, json={})))
    with pytest.raises(SensitivityError):
        Router({"triage": p}).route("triage", "private")


def test_remote_ollama_blocked_for_private_data():
    p = OllamaProvider(model="m", base_url="http://10.0.0.5:11434", client=client_with(lambda r: httpx.Response(200, json={})))
    with pytest.raises(SensitivityError):
        Router({"triage": p}).route("triage", "private")


def test_openai_compat_sends_bearer_and_parses_choice():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi there"}}]})

    p = OpenAICompatProvider(base_url="https://api.example.com/v1", api_key=SECRET, model="m", client=client_with(handler))
    assert p.complete("hello", system="sys") == "hi there"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"]["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    assert p.is_local is False


def test_api_key_not_in_error_messages_or_repr():
    def handler(req):
        return httpx.Response(401, json={"error": "bad key"})

    p = OpenAICompatProvider(base_url="https://api.example.com/v1", api_key=SECRET, model="m", client=client_with(handler))
    with pytest.raises(ProviderError) as e:
        p.complete("x")
    assert SECRET not in str(e.value)
    assert SECRET not in repr(p) and SECRET not in str(p)
    assert "401" in str(e.value)


def test_network_error_wrapped_as_provider_error():
    def handler(req):
        raise httpx.ConnectError("refused")

    p = OllamaProvider(model="qwen", client=client_with(handler))
    with pytest.raises(ProviderError):
        p.complete("x")


def test_malformed_response_body_wrapped_as_provider_error():
    p = OpenAICompatProvider(base_url="https://x/v1", api_key=SECRET, model="m",
                             client=client_with(lambda req: httpx.Response(200, json={"unexpected": 1})))
    with pytest.raises(ProviderError):
        p.complete("x")


def test_complete_json_parses_fenced_json():
    p = FakeProvider(['Sure!\n```json\n{"topic": "infra/sre", "score": 7}\n```'])
    assert complete_json(p, "q", Out) == Out(topic="infra/sre", score=7)


def test_complete_json_parses_json_after_prose_with_braces_in_strings():
    p = FakeProvider(['Here you go: {"topic": "a {b} c", "score": 1} thanks'])
    assert complete_json(p, "q", Out).topic == "a {b} c"


def test_complete_json_retries_once_then_raises():
    p = FakeProvider(["not json", '{"topic": "x"}'])
    with pytest.raises(LLMOutputError):
        complete_json(p, "q", Out)
    assert len(p.prompts) == 2


def test_complete_json_retry_prompt_mentions_previous_error_and_succeeds():
    p = FakeProvider(["nope", '{"topic": "t", "score": 3}'])
    out = complete_json(p, "original prompt", Out)
    assert out.score == 3
    assert "original prompt" in p.prompts[1] and "invalid" in p.prompts[1].lower()


def test_complete_json_rejects_wrong_types():
    p = FakeProvider(['{"topic": "t", "score": "high"}', '{"topic": "t", "score": "high"}'])
    with pytest.raises(LLMOutputError):
        complete_json(p, "q", Out)


def test_complete_json_retries_zero_means_single_call():
    p = FakeProvider(["junk"])
    with pytest.raises(LLMOutputError):
        complete_json(p, "q", Out, retries=0)
    assert len(p.prompts) == 1


def test_complete_json_passes_system_prompt():
    p = FakeProvider(['{"topic": "t", "score": 1}'])
    complete_json(p, "q", Out, system="only json")
    assert p.systems == ["only json"]


def test_route_private_to_cloud_raises_sensitivity_error():
    cloud = FakeProvider([], is_local=False, name="cloud")
    r = Router({"extract": cloud})
    with pytest.raises(SensitivityError):
        r.route("extract", "private")


def test_route_default_sensitivity_is_private():
    r = Router({"extract": FakeProvider([], is_local=False)})
    with pytest.raises(SensitivityError):
        r.route("extract")


def test_route_public_to_cloud_ok_and_private_to_local_ok():
    cloud = FakeProvider([], is_local=False)
    local = FakeProvider([], is_local=True)
    r = Router({"extract": cloud, "triage": local})
    assert r.route("extract", "public") is cloud
    assert r.route("triage", "private") is local


def test_route_unknown_task_raises_key_error():
    with pytest.raises(KeyError):
        Router({}).route("nope", "public")


def test_build_router_defaults_to_ollama_and_requires_model():
    with pytest.raises(ConfigError):
        build_router({})
    r = build_router({"SB_OLLAMA_MODEL": "qwen2.5:7b"})
    assert r.route("triage", "private").is_local is True
    assert r.route("synthesis", "private").is_local is True


def test_build_router_cloud_route_needs_key_and_model():
    env = {"SB_OLLAMA_MODEL": "m", "SB_ROUTE_EXTRACT": "groq"}
    with pytest.raises(ConfigError):
        build_router(env)
    env.update({"SB_GROQ_API_KEY": SECRET, "SB_GROQ_MODEL": "llama"})
    r = build_router(env)
    assert r.route("extract", "public").is_local is False
    with pytest.raises(SensitivityError):
        r.route("extract", "private")


def test_build_router_unknown_provider_name_raises_config_error():
    with pytest.raises(ConfigError):
        build_router({"SB_OLLAMA_MODEL": "m", "SB_ROUTE_TRIAGE": "skynet"})


def test_config_error_does_not_leak_keys():
    env = {"SB_OLLAMA_MODEL": "m", "SB_ROUTE_EXTRACT": "gemini", "SB_GEMINI_API_KEY": SECRET}
    with pytest.raises(ConfigError) as e:
        build_router(env)
    assert SECRET not in str(e.value)
