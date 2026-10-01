"""LiteLLM chat call with structured outputs: OpenRouter (Cerebras) or Gemini.

Provider selection (env LLM_PROVIDER):
- "openrouter": openrouter/openai/gpt-oss-120b pinned to Cerebras.
- "gemini":     gemini/gemini-2.5-flash, or env LLM_MODEL.
- "auto" (default): OpenRouter if OPENROUTER_API_KEY is set, else Gemini if GEMINI_API_KEY
  is set. If OpenRouter fails with an auth/credit error and a Gemini key exists, Gemini is
  tried once.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

from .schema import LLMResponse

logger = logging.getLogger(__name__)

Provider = Literal["openrouter", "gemini"]

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
GEMINI_DEFAULT_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_TIMEOUT = 30.0

# Errors that mean "this provider/account can't serve us" rather than "the request failed".
_FALLBACK_STATUS = {400, 401, 402, 403}
_FALLBACK_ERRORS = {"AuthenticationError", "BadRequestError", "PermissionDeniedError"}


class LLMError(RuntimeError):
    """The LLM call itself failed (config, network, provider error, timeout)."""


def is_mock_mode() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() in ("1", "true", "yes", "on")


def _timeout() -> float:
    try:
        return float(os.environ.get("LLM_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _has_key(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def gemini_model() -> str:
    return os.environ.get("LLM_MODEL", "").strip() or GEMINI_DEFAULT_MODEL


def provider_chain() -> list[Provider]:
    """Providers to try, in order. Raises LLMError when none is usable."""
    choice = os.environ.get("LLM_PROVIDER", "").strip().lower() or "auto"
    if choice == "openrouter":
        if not _has_key("OPENROUTER_API_KEY"):
            raise LLMError("LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set")
        return ["openrouter"]
    if choice == "gemini":
        if not _has_key("GEMINI_API_KEY"):
            raise LLMError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return ["gemini"]
    if choice != "auto":
        raise LLMError(f"Unknown LLM_PROVIDER {choice!r} (expected openrouter, gemini or auto)")
    chain: list[Provider] = []
    if _has_key("OPENROUTER_API_KEY"):
        chain.append("openrouter")
    if _has_key("GEMINI_API_KEY"):
        chain.append("gemini")
    if not chain:
        raise LLMError("No LLM API key set (OPENROUTER_API_KEY or GEMINI_API_KEY)")
    return chain


def is_fallback_error(exc: BaseException) -> bool:
    """Auth/credit/bad-request failures that justify switching provider."""
    if type(exc).__name__ in _FALLBACK_ERRORS:
        return True
    return getattr(exc, "status_code", None) in _FALLBACK_STATUS


def _load_completion():
    """Import litellm lazily (it is slow to import); cached by Python after the first call."""
    # Use litellm's bundled model cost map instead of fetching it from GitHub on import.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    litellm.suppress_debug_info = True  # no "Give Feedback" banner on stdout per error
    return litellm.completion


async def warm_up() -> None:
    """Import litellm in a worker thread so the first chat isn't charged the import time.
    Safe to fire-and-forget from the app lifespan; no-op in mock mode."""
    if is_mock_mode():
        return
    try:
        await asyncio.to_thread(_load_completion)
    except Exception:  # a broken install surfaces later as an apologetic chat reply
        pass


def _complete(provider: Provider, messages: list[dict], timeout: float) -> str:
    completion = _load_completion()
    if provider == "openrouter":
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            timeout=timeout,
        )
    else:
        response = completion(
            model=gemini_model(),
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            drop_params=True,  # drop reasoning_effort on models that don't support it
            timeout=timeout,
        )
    return response.choices[0].message.content or ""


async def _call_provider(provider: Provider, messages: list[dict], timeout: float) -> str:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_complete, provider, messages, timeout), timeout=timeout + 5
        )
    except asyncio.TimeoutError as exc:
        raise LLMError(f"LLM request to {provider} timed out") from exc


async def call_llm(messages: list[dict]) -> str:
    """Return the raw content of the model's reply. Raises LLMError on any failure."""
    chain = provider_chain()
    timeout = _timeout()
    try:
        # The import is not part of the request budget: it can be slow on a cold disk.
        await asyncio.to_thread(_load_completion)
    except Exception as exc:
        raise LLMError(f"LLM client unavailable: {type(exc).__name__}") from exc

    for i, provider in enumerate(chain):
        has_next = i + 1 < len(chain)
        try:
            content = await _call_provider(provider, messages, timeout)
        except LLMError:
            raise
        except Exception as exc:  # litellm raises many provider-specific types
            status = getattr(exc, "status_code", None)
            if has_next and is_fallback_error(exc):
                logger.warning("LLM provider %s failed (%s, status %s); falling back to %s",
                               provider, type(exc).__name__, status, chain[i + 1])
                continue
            raise LLMError(f"LLM request to {provider} failed: {type(exc).__name__}") from exc
        model = MODEL if provider == "openrouter" else gemini_model()
        logger.info("LLM response from provider=%s model=%s", provider, model)
        return content
    raise LLMError("No LLM provider succeeded")  # unreachable: chain is never empty
