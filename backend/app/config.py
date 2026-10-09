from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    QDRANT_URL: str
    QDRANT_PORT: int = 6333
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PRIMARY_MODEL: str = "google/gemini-3.8-flash"
    FAST_MODEL: str = "google/gemini-2.5-flash-lite"
    EMBEDDING_MODEL: str = "google/gemini-embedding-2"
    EMBEDDING_DIMENSIONS: int = 1536
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str
    JWT_SECRET: str
    FRONTEND_URLS: str = ""
    BACKEND_URL: str = ""
    FORGE_MCP_URL: str = ""
    FORGE_API_KEY: str = ""
    VESTI_API_URL: str = ""
    VESTI_API_KEY: str = ""
    GLOWUP_MCP_URL: str = ""
    GLOWUP_MCP_API_KEY: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
