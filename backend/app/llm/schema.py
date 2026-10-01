"""Structured-output schema the LLM must follow, plus a lenient parser for its replies.

The models are kept strict-schema friendly (every field required, no numeric
constraints, enums via Literal) so providers that enforce JSON Schema accept them.
Semantic checks (quantity > 0, valid ticker) happen at execution time instead.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class TradeInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[TradeInstruction]
    watchlist_changes: list[WatchlistInstruction]


class LLMParseError(ValueError):
    """The model's reply could not be turned into an LLMResponse."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap the object in prose; fall back to the outermost braces.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMParseError("response is not JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"response is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise LLMParseError("response JSON is not an object")
    return data


def _lenient_items(items: object, model: type[BaseModel]) -> list:
    """Validate each list item on its own, dropping (and logging) the bad ones."""
    if not isinstance(items, list):
        return []
    valid = []
    for item in items:
        if isinstance(item, dict):
            item = {k: v.lower() if k in ("side", "action") and isinstance(v, str) else v
                    for k, v in item.items()}
        try:
            valid.append(model.model_validate(item))
        except ValidationError as exc:
            logger.warning("Dropping malformed %s from LLM: %r (%s)", model.__name__, item, exc)
    return valid


def parse_llm_response(raw: str | None) -> LLMResponse:
    """Parse the raw model output. Missing action lists default to empty; malformed
    individual actions are dropped; a missing/empty message raises LLMParseError."""
    if not raw or not raw.strip():
        raise LLMParseError("empty response")
    data = _extract_json(raw)
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        raise LLMParseError("response has no message")
    return LLMResponse(
        message=message.strip(),
        trades=_lenient_items(data.get("trades"), TradeInstruction),
        watchlist_changes=_lenient_items(data.get("watchlist_changes"), WatchlistInstruction),
    )
