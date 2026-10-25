import json
import time
from dataclasses import dataclass

import anthropic
import openai
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..domain import ModelSpec

MODELS: dict[str, ModelSpec] = {
    "sonnet-5.5": ModelSpec(
        key="sonnet-5.5",
        provider="anthropic",
        model_id="claude-sonnet-5-5",
        price_in_usd_per_mtok=2.0,
        price_out_usd_per_mtok=10.0,
        label="Claude Sonnet 5.5",
    ),
    "haiku-5.5": ModelSpec(
        key="haiku-5.5",
        provider="anthropic",
        model_id="claude-haiku-5-5",
        price_in_usd_per_mtok=0.10,
        price_out_usd_per_mtok=0.50,
        label="Claude Haiku 5.5",
    ),
    "nemotron-ultra-free": ModelSpec(
        key="nemotron-ultra-free",
        provider="openrouter",
        model_id="nvidia/nemotron-3-ultra-550b-a55b:free",
        price_in_usd_per_mtok=0.0,
        price_out_usd_per_mtok=0.0,
        label="Nemotron Ultra (darmowy)",
    ),
}
DEFAULT_MODEL = "haiku-5.5"

MAX_TOKENS = 32000
# błędy dostawców, które zostają po ponowieniach klienta (HTTP 4xx/5xx, przekroczenie czasu, brak połączenia)
PROVIDER_ERRORS: tuple[type[Exception], ...] = (anthropic.APIError, openai.APIError)

_TIMEOUT_S = 300
_MAX_RETRIES = 3
_OPENROUTER_URL = "https://openrouter.ai/api/v1"


def make_chat_model(spec: ModelSpec, settings: Settings) -> BaseChatModel:
    """Jedyne miejsce, które zna dostawcę. Bez `temperature`: ustawienia domyślne dostawcy."""
    if spec.provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Brak klucza API: ustaw ANTHROPIC_API_KEY w pliku .env.")
        return ChatAnthropic(
            model=spec.model_id,
            api_key=settings.anthropic_api_key,
            max_tokens=MAX_TOKENS,
            max_retries=_MAX_RETRIES,
            timeout=_TIMEOUT_S,
        )
    if not settings.openrouter_api_key:
        raise ValueError("Brak klucza API: ustaw OPENROUTER_API_KEY w pliku .env.")
    return ChatOpenAI(
        model=spec.model_id,
        base_url=_OPENROUTER_URL,
        api_key=settings.openrouter_api_key,
        max_tokens=MAX_TOKENS,
        max_retries=_MAX_RETRIES,
        timeout=_TIMEOUT_S,
    )


@dataclass(frozen=True)
class CallOutcome:
    parsed: BaseModel | None
    raw_json: str | None
    parse_error: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    reasoning_tokens: int | None = None
    stop_reason: str | None = None
    reply_text: str | None = None  # tekst odpowiedzi bez wywołania narzędzia, skrócony


TRUNCATED = "Odpowiedź ucięta: przekroczono limit tokenów."
_TRUNCATION_REASONS = ("max_tokens", "length")
_REPLY_TEXT_LIMIT = 2000


def call_structured(
    chat: BaseChatModel, schema: type[BaseModel], messages: list[BaseMessage]
) -> CallOutcome:
    """Schemat jako jedyne narzędzie z `tool_choice="auto"`, identycznie dla każdego dostawcy.

    Wymuszony wybór narzędzia odrzuca Sonnet 5.5 i nie działa z myśleniem Haiku 5.5, więc
    polecenie wywołania narzędzia jest w szablonie prompta, a argumenty parsuje się tutaj.
    """
    name = schema.__name__
    bound = chat.bind_tools([schema], tool_choice="auto")
    started = time.perf_counter()
    reply = bound.invoke(messages)
    latency_ms = round((time.perf_counter() - started) * 1000)

    usage = getattr(reply, "usage_metadata", None)
    meta = getattr(reply, "response_metadata", None) or {}
    stop_reason = meta.get("stop_reason") or meta.get("finish_reason")
    parsed: BaseModel | None = None
    raw_json: str | None = None
    reply_text: str | None = None
    error: str | None = None
    # przy kilku wywołaniach narzędzia liczy się pierwsze
    calls = [c for c in getattr(reply, "tool_calls", []) if c["name"] == name]
    invalid = [c for c in getattr(reply, "invalid_tool_calls", []) if c["name"] == name]
    if calls:
        raw_json = json.dumps(calls[0]["args"], ensure_ascii=False)
    elif invalid:
        raw_json = invalid[0].get("args")
        error = invalid[0].get("error") or "Argumenty narzędzia nie są poprawnym JSON-em."
    else:
        error = f"Model nie wywołał narzędzia {name}."
        reply_text = _text(reply)[:_REPLY_TEXT_LIMIT] or None
    if stop_reason in _TRUNCATION_REASONS:
        error = TRUNCATED
    elif raw_json is not None and error is None:
        try:
            parsed = schema.model_validate(calls[0]["args"])
        except ValidationError as e:
            error = compact_errors(e)
    return CallOutcome(
        parsed=parsed,
        raw_json=raw_json,
        parse_error=error,
        input_tokens=usage.get("input_tokens") if usage else None,
        output_tokens=usage.get("output_tokens") if usage else None,
        latency_ms=latency_ms,
        reasoning_tokens=(usage.get("output_token_details") or {}).get("reasoning") if usage else None,
        stop_reason=stop_reason,
        reply_text=reply_text,
    )


def compact_errors(error: ValidationError) -> str:
    """Błędy walidacji jako „ścieżka: komunikat” rozdzielone średnikami, bez wartości wejściowych i adresów."""
    parts = []
    for e in error.errors(include_url=False, include_input=False):
        loc = ".".join(str(x) for x in e["loc"])
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return "; ".join(parts)


def _text(reply: BaseMessage) -> str:
    content = reply.content
    if isinstance(content, str):
        return content.strip()
    texts = [
        b if isinstance(b, str) else b.get("text", "")
        for b in content
        if isinstance(b, str) or b.get("type") == "text"
    ]
    return "\n".join(t for t in texts if t).strip()


def cost_usd(spec: ModelSpec, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    return (
        input_tokens * spec.price_in_usd_per_mtok + output_tokens * spec.price_out_usd_per_mtok
    ) / 1_000_000
