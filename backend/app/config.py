from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str
    QDRANT_URL: str
    QDRANT_PORT: int = 6333
    GEMINI_API_KEY: str
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
