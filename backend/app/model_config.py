import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
load_dotenv(override=True)


DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_PROVIDERS = {
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "base_url_env": "GEMINI_BASE_URL",
        "default_base_url": DEFAULT_GEMINI_BASE_URL,
        "model_env": "GEMINI_MODEL",
        "memory_model_env": "GEMINI_MEMORY_MODEL",
        "default_model": DEFAULT_GEMINI_MODEL,
        "model_prefix": "gemini",
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "model_env": "DEEPSEEK_MODEL",
        "memory_model_env": "DEEPSEEK_MEMORY_MODEL",
        "default_model": DEFAULT_DEEPSEEK_MODEL,
        "model_prefix": "deepseek",
    },
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "base_url_env": "GROQ_BASE_URL",
        "default_base_url": DEFAULT_GROQ_BASE_URL,
        "model_env": "GROQ_MODEL",
        "memory_model_env": "GROQ_MEMORY_MODEL",
        "default_model": DEFAULT_GROQ_MODEL,
        "model_prefix": "",
    },
}


def get_llm_provider() -> str:
    provider = (os.getenv("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        supported = ", ".join(sorted(_PROVIDERS))
        raise RuntimeError(f"Unsupported LLM_PROVIDER '{provider}'. Use: {supported}")
    return provider


def get_llm_model_name(memory: bool = False) -> str:
    provider = get_llm_provider()
    return _get_model_name_for_provider(provider, memory)


def create_llm_client() -> AsyncOpenAI:
    provider = get_llm_provider()
    return _create_client_for_provider(provider)


def get_gemini_model_name(memory: bool = False) -> str:
    return _get_model_name_for_provider("gemini", memory)


def create_gemini_client() -> AsyncOpenAI:
    return _create_client_for_provider("gemini")


def _get_model_name_for_provider(provider: str, memory: bool = False) -> str:
    config = _PROVIDERS[provider]
    env_name = config["memory_model_env"] if memory else config["model_env"]
    model = os.getenv(env_name) or config["default_model"]
    if config["model_prefix"] and not model.lower().startswith(config["model_prefix"]):
        raise RuntimeError(f"{env_name} must be a {provider} model")
    return model


def _create_client_for_provider(provider: str) -> AsyncOpenAI:
    config = _PROVIDERS[provider]
    api_key = os.getenv(config["api_key_env"])
    if not api_key:
        raise RuntimeError(f"{config['api_key_env']} is missing")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv(config["base_url_env"]) or config["default_base_url"],
    )


def llm_is_configured() -> bool:
    return bool(os.getenv(_PROVIDERS[get_llm_provider()]["api_key_env"]))
