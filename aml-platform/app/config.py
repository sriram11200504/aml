from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Dict
import os


class Settings(BaseSettings):
    model_api_url: str = "http://localhost:8200"
    use_sqlite: bool = True
    database_url: str = "sqlite+aiosqlite:///./data/aml.db"

    host: str = "0.0.0.0"
    port: int = 8100
    dashboard_origin: str = "http://localhost:4000"

    # Format: "key1=bank_id1,key2=bank_id2"
    ingest_api_keys: str = "aml-secret-key-01=fakebank-01"

    # Format: "bank_id=url:key,bank_id2=url2:key2"
    bank_compliance_configs: str = "fakebank-01=http://localhost:8000:compliance-secret-key-01"

    threshold_medium: float = 0.4
    threshold_high: float = 0.6
    threshold_critical: float = 0.8

    postgres_user: str = "amluser"
    postgres_password: str = "amlpass"
    postgres_db: str = "amldb"
    postgres_host: str = "localhost"
    postgres_port: int = 5434

    model_config = {"env_file": ".env", "case_sensitive": False}

    def get_db_url(self) -> str:
        if self.use_sqlite:
            url = self.database_url
            if url.startswith("sqlite:///"):
                url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
            elif not url.startswith("sqlite+aiosqlite:///"):
                url = "sqlite+aiosqlite:///./data/aml.db"
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def parse_ingest_keys(self) -> Dict[str, str]:
        """Returns {api_key: bank_id}."""
        result = {}
        for pair in self.ingest_api_keys.split(","):
            pair = pair.strip()
            if "=" in pair:
                key, bank_id = pair.split("=", 1)
                result[key.strip()] = bank_id.strip()
        return result

    def parse_bank_compliance(self) -> Dict[str, Dict]:
        """Returns {bank_id: {url: ..., key: ...}}."""
        result = {}
        for pair in self.bank_compliance_configs.split(","):
            pair = pair.strip()
            if "=" in pair:
                bank_id, rest = pair.split("=", 1)
                # rest is url:key but url might have colons (http://...)
                # split from right to get key
                parts = rest.rsplit(":", 1)
                if len(parts) == 2:
                    url, key = parts
                    result[bank_id.strip()] = {"url": url.strip(), "key": key.strip()}
        return result

    def risk_level(self, score: float) -> str:
        if score >= self.threshold_critical:
            return "Critical"
        if score >= self.threshold_high:
            return "High"
        if score >= self.threshold_medium:
            return "Medium"
        return "Low"


@lru_cache
def get_settings() -> Settings:
    return Settings()
