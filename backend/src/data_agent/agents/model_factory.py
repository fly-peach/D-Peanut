"""model_factory — the single point where 'model is never hardcoded' is realised.

RunSettings -> a pydantic_ai Model instance, constructed per run (settings edits
take effect with no restart). provider="test" returns TestModel so CI and offline
demos run the full loop without any key.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import ModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .deps import RunSettings

PRESET_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot": "https://api.moonshot.cn/v1",
}


def build_model(settings: RunSettings, api_key: str | None) -> Any:
    provider = (settings.provider or "test").lower()
    if provider == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel(model_name=settings.model_name or "test")
    base_url = settings.base_url or PRESET_BASE_URLS.get(provider, "")
    model_name = settings.model_name or _default_model(provider)
    if not base_url:
        raise ValueError(f"unknown provider {provider!r} and no base_url given")
    provider = OpenAIProvider(base_url=base_url, api_key=api_key or "unset")
    return OpenAIChatModel(model_name, provider=provider)


def model_settings(settings: RunSettings) -> ModelSettings:
    return ModelSettings(temperature=settings.temperature, max_tokens=settings.max_tokens)


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-4.1", "deepseek": "deepseek-chat", "dashscope": "qwen-plus",
        "zhipu": "glm-4-plus", "moonshot": "moonshot-v1-32k",
    }.get(provider, "")


async def ping_model(settings: RunSettings, api_key: str | None) -> dict:
    """POST /api/settings/llm/test — one minimal real request, errors surfaced."""
    import time

    from pydantic_ai import Agent

    t0 = time.monotonic()
    try:
        agent = Agent(build_model(settings, api_key), output_type=str)
        result = await agent.run("ping", model_settings=ModelSettings(max_tokens=16))
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000),
                "model": settings.model_name or settings.provider, "error": None,
                "echo": (result.output or "")[:40]}
    except Exception as e:  # noqa: BLE001 — test endpoint must report, not crash
        return {"ok": False, "latency_ms": int((time.monotonic() - t0) * 1000),
                "model": settings.model_name or settings.provider,
                "error": f"{type(e).__name__}: {str(e)[:300]}"}
