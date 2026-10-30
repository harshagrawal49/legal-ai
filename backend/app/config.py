from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://nyaya:nyaya@localhost:5433/nyaya"

    # Any OpenAI-compatible LLM API. Default: Google Gemini (free tier; key from https://aistudio.google.com/apikey).
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    # Main model: search analysis and chat. Fast model: intake, document extraction, brief suggestions
    # (shorter, well-structured tasks where a lighter model is much quicker). Bulk model: per-judgment
    # summaries at ingestion.
    model_main: str = "gemini-3.8-flash"
    model_fast: str = "gemini-3.5-flash-lite"
    model_bulk: str = "gemini-3.5-flash-lite"

    # Thinking models spend most of their time reasoning before answering; "low" keeps that short.
    # Sent as `reasoning_effort`; leave empty for providers that don't support it.
    llm_reasoning_effort: str = "low"
    # Fail fast instead of silently waiting minutes on free-tier rate limits.
    llm_max_retries: int = 2
    llm_timeout_seconds: int = 90

    # Local embedding model (runs on CPU via fastembed, no API key needed).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # How many candidate judgments go to the LLM for relevance analysis, and how many are kept.
    search_candidates: int = 8
    search_results: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
