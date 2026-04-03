"""Cached LLM client factory."""

import re
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    kwargs: dict = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "base_url": settings.openai_api_base,
        "streaming": True,
    }
    if "reasoner" not in settings.openai_model:
        kwargs["temperature"] = 0
    return ChatOpenAI(**kwargs)


def extract_json(text: str) -> str:
    """Extract JSON from LLM output, handling markdown code fences."""
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0).strip()
    return text.strip()
