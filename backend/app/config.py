from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://nyaya:nyaya@localhost:5433/nyaya"

    # Any OpenAI-compatible LLM API. Default: Google Gemini (free tier; key from https://aistudio.google.com/apikey).
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    # Main model: intake, search analysis, chat. Bulk model: per-judgment summaries at ingestion.
    model_main: str = "gemini-3.8-flash"
    model_bulk: str = "gemini-3.5-flash-lite"

    # Local embedding model (runs on CPU via fastembed, no API key needed).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # How many candidate judgments go to the LLM for relevance analysis, and how many are kept.
    search_candidates: int = 15
    search_results: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
