from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    bank_id: str = "fakebank-01"
    use_sqlite: bool = True
    database_url: str = "sqlite+aiosqlite:///./data/bank.db"

    # AML
    aml_url: str = "http://localhost:8100"
    aml_api_key: str = "aml-secret-key-01"

    # Compliance
    compliance_api_key: str = "compliance-secret-key-01"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    # Postgres
    postgres_user: str = "bankuser"
    postgres_password: str = "bankpass"
    postgres_db: str = "bankdb"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    model_config = {"env_file": ".env", "case_sensitive": False}

    def get_db_url(self) -> str:
        if self.use_sqlite:
            url = self.database_url
            if url.startswith("sqlite:///"):
                url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
            elif not url.startswith("sqlite+aiosqlite:///"):
                url = "sqlite+aiosqlite:///./data/bank.db"
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_sync_db_url(self) -> str:
        if self.use_sqlite:
            return "sqlite:///./data/bank.db"
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
