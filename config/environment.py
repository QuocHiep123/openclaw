"""
Environment helpers — LLM client factories.
"""
from __future__ import annotations

import random

from langchain_core.language_models import BaseChatModel

from config.settings import settings


def get_llm(temperature: float = 0.3) -> BaseChatModel:
    """Return the configured LLM instance."""
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            temperature=temperature,
            api_key=settings.openai_api_key,
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        key_pool = settings.google_api_key_pool
        if not key_pool:
            raise ValueError("No Google API key configured. Set GOOGLE_API_KEY or GOOGLE_API_KEYS in .env")

        selected_key = random.choice(key_pool)

        return ChatGoogleGenerativeAI(
            model=settings.llm_model,
            temperature=temperature,
            google_api_key=selected_key,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
