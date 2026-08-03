from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://propel:propel123@postgres:5432/propel_grid"
    REDIS_URL: str = "redis://redis:6379/0"

    POSTGRES_USER: str = "propel"
    POSTGRES_PASSWORD: str = "propel123"
    POSTGRES_DB: str = "propel_grid"


settings = Settings()
