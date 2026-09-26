from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    UPLOAD_DIR: str = "uploads"
    EXPORT_DIR: str = "exports"
    DATABASE_URL: str = "sqlite:///./synthgen.db"
    MAX_UPLOAD_SIZE_MB: int = 50
    CTGAN_EPOCHS: int = 300
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Ensure directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.EXPORT_DIR, exist_ok=True)
