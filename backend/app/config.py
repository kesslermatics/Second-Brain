from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    QDRANT_URL: str
    QDRANT_PORT: int = 6333
    OPENAI_API_KEY: str
    OPENAI_PRIMARY_MODEL: str = "gpt-5.6-sol"
    OPENAI_FAST_MODEL: str = "gpt-5.6-luna"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIMENSIONS: int = 1024
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str
    JWT_SECRET: str
    FRONTEND_URLS: str = ""
    BACKEND_URL: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
