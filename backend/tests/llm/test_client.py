"""Provider selection, OpenRouter -> Gemini fallback and per-provider call arguments.

litellm.completion is replaced by a fake; nothing touches the network.
"""
from __future__ import annotations

import pytest

from app.llm import client
from app.llm.client import (
    EXTRA_BODY,
    GEMINI_DEFAULT_MODEL,
    MODEL,
    LLMError,
    call_llm,
    provider_chain,
)
from app.llm.schema import LLMResponse

REPLY = '{"message": "ok", "trades": [], "watchlist_changes": []}'
MESSAGES = [{"role": "user", "content": "What's in my portfolio?"}]


class APIError(Exception):
    """Mimics litellm.APIError carrying an HTTP status (e.g. OpenRouter's 402)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class AuthenticationError(Exception):
    pass


class ServiceUnavailableError(Exception):
    status_code = 503


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_completion(monkeypatch):
    """Records each call's kwargs; `errors` maps model -> exception to raise."""

    class Fake:
        def __init__(self):
            self.calls: list[dict] = []
            self.errors: dict[str, Exception] = {}

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["model"] in self.errors:
                raise self.errors[kwargs["model"]]
            message = type("Msg", (), {"content": REPLY})()
            choice = type("Choice", (), {"message": message})()
            return type("Resp", (), {"choices": [choice]})()

        @property
        def models(self):
            return [c["model"] for c in self.calls]

    fake = Fake()
    monkeypatch.setattr(client, "_load_completion", lambda: fake)
    return fake


# --- provider selection -------------------------------------------------------------

@pytest.mark.parametrize("provider, keys, expected", [
    (None, {"OPENROUTER_API_KEY", "GEMINI_API_KEY"}, ["openrouter", "gemini"]),
    (None, {"OPENROUTER_API_KEY"}, ["openrouter"]),
    (None, {"GEMINI_API_KEY"}, ["gemini"]),
    ("auto", {"OPENROUTER_API_KEY", "GEMINI_API_KEY"}, ["openrouter", "gemini"]),
    ("AUTO", {"GEMINI_API_KEY"}, ["gemini"]),
    ("openrouter", {"OPENROUTER_API_KEY", "GEMINI_API_KEY"}, ["openrouter"]),
    ("openrouter", {"OPENROUTER_API_KEY"}, ["openrouter"]),
    ("gemini", {"OPENROUTER_API_KEY", "GEMINI_API_KEY"}, ["gemini"]),
    ("gemini", {"GEMINI_API_KEY"}, ["gemini"]),
])
def test_provider_chain(monkeypatch, provider, keys, expected):
    if provider is not None:
        monkeypatch.setenv("LLM_PROVIDER", provider)
    for key in keys:
        monkeypatch.setenv(key, "test-key")
    assert provider_chain() == expected


@pytest.mark.parametrize("provider, keys", [
    (None, set()),
    ("auto", set()),
    ("openrouter", {"GEMINI_API_KEY"}),
    ("gemini", {"OPENROUTER_API_KEY"}),
    ("claude", {"OPENROUTER_API_KEY", "GEMINI_API_KEY"}),
])
def test_provider_chain_unusable(monkeypatch, provider, keys):
    if provider is not None:
        monkeypatch.setenv("LLM_PROVIDER", provider)
    for key in keys:
        monkeypatch.setenv(key, "test-key")
    with pytest.raises(LLMError):
        provider_chain()


def test_blank_key_counts_as_unset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  ")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert provider_chain() == ["gemini"]


# --- call arguments -----------------------------------------------------------------

async def test_openrouter_call_unchanged(monkeypatch, fake_completion):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert await call_llm(MESSAGES) == REPLY
    (call,) = fake_completion.calls
    assert call["model"] == MODEL
    assert call["extra_body"] == EXTRA_BODY
    assert call["reasoning_effort"] == "low"
    assert call["response_format"] is LLMResponse
    assert call["messages"] == MESSAGES


async def test_gemini_call_has_no_extra_body(monkeypatch, fake_completion):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert await call_llm(MESSAGES) == REPLY
    (call,) = fake_completion.calls
    assert call["model"] == GEMINI_DEFAULT_MODEL
    assert "extra_body" not in call
    assert call["response_format"] is LLMResponse
    assert call["drop_params"] is True


async def test_llm_model_overrides_gemini_only(monkeypatch, fake_completion):
    monkeypatch.setenv("LLM_MODEL", "gemini/gemini-2.0-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_completion.errors[MODEL] = APIError(402)
    await call_llm(MESSAGES)
    assert fake_completion.models == [MODEL, "gemini/gemini-2.0-flash"]


# --- auto fallback ------------------------------------------------------------------

@pytest.mark.parametrize("error", [APIError(402), APIError(401), AuthenticationError("bad key")])
async def test_auto_falls_back_to_gemini(monkeypatch, fake_completion, error, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret-value")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-secret-value")
    fake_completion.errors[MODEL] = error
    caplog.set_level("INFO", logger="app.llm.client")

    assert await call_llm(MESSAGES) == REPLY
    assert fake_completion.models == [MODEL, GEMINI_DEFAULT_MODEL]
    assert "extra_body" not in fake_completion.calls[1]
    assert "provider=gemini" in caplog.text
    assert "secret-value" not in caplog.text


async def test_no_fallback_on_other_errors(monkeypatch, fake_completion):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_completion.errors[MODEL] = ServiceUnavailableError("down")
    with pytest.raises(LLMError):
        await call_llm(MESSAGES)
    assert fake_completion.models == [MODEL]


async def test_no_fallback_when_provider_forced(monkeypatch, fake_completion):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_completion.errors[MODEL] = APIError(402)
    with pytest.raises(LLMError):
        await call_llm(MESSAGES)
    assert fake_completion.models == [MODEL]


async def test_402_without_gemini_key_is_llm_error(monkeypatch, fake_completion):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    fake_completion.errors[MODEL] = APIError(402)
    with pytest.raises(LLMError):
        await call_llm(MESSAGES)


async def test_gemini_failure_after_fallback_is_llm_error(monkeypatch, fake_completion):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake_completion.errors[MODEL] = APIError(402)
    fake_completion.errors[GEMINI_DEFAULT_MODEL] = APIError(401)
    with pytest.raises(LLMError):
        await call_llm(MESSAGES)
    assert fake_completion.models == [MODEL, GEMINI_DEFAULT_MODEL]


async def test_mock_mode_short_circuits_providers(monkeypatch, fake_llm, price_cache, market_source):
    from app.llm.service import handle_chat

    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    body = await handle_chat("hello", price_cache, market_source)
    assert body["message"].startswith("Mock response")
    assert fake_llm.calls == []
