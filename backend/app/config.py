from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://propel:propel123@postgres:5432/propel_grid"
    REDIS_URL: str = "redis://redis:6379/0"

    POSTGRES_USER: str = "propel"
    POSTGRES_PASSWORD: str = "propel123"
    POSTGRES_DB: str = "propel_grid"

    @model_validator(mode="after")
    def _fix_urls(self):
        """Render provides ``postgresql://`` but asyncpg needs
        ``postgresql+asyncpg://``.  Render Redis may also lack the
        ``redis://`` scheme.  Auto-convert both so deployment works
        without manual env-var editing."""
        # --- PostgreSQL ---
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            self.DATABASE_URL = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            self.DATABASE_URL = url.replace("postgres://", "postgresql+asyncpg://", 1)

        # --- Redis ---
        rurl = self.REDIS_URL
        if rurl and not rurl.startswith(("redis://", "rediss://", "unix://")):
            # Render sometimes gives URLs without scheme or with 'red://'
            if rurl.startswith("red://"):
                self.REDIS_URL = rurl.replace("red://", "redis://", 1)
            else:
                self.REDIS_URL = f"redis://{rurl}"
        return self


settings = Settings()

