"""OpenRouter chat-model factory. Sole owner of LLM provider configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

load_dotenv()

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def get_chat_model() -> BaseChatModel:
    """Return a ChatOpenAI bound to OpenRouter + DeepSeek V4 Flash (model id from env)."""
    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL),
        base_url=_OPENROUTER_BASE_URL,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        temperature=0,
    )
