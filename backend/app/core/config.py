"""Application settings, loaded from environment variables (or a local .env file).

Secrets (JWT key, database passwords) have no defaults on purpose: the service
refuses to start without them rather than running with a guessable value.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OmniData Analytics & Sync Platform"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    # --- auth -----------------------------------------------------------------
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=60, ge=1, le=1440)
    # Password for the demo accounts created on first start (empty DB only).
    demo_password: SecretStr = Field(min_length=12)

    # --- MS SQL Server (source data + migration state) --------------------------
    mssql_host: str = "localhost"
    mssql_port: int = 1433
    mssql_user: str = "sa"
    mssql_password: SecretStr
    mssql_database: str = "omnidata_source"

    # --- PostgreSQL (analytical ingestion) --------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "omnidata"
    postgres_password: SecretStr
    postgres_database: str = "omnidata"

    # --- MySQL (access control) --------------------------------------------------
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "omnidata"
    mysql_password: SecretStr
    mysql_database: str = "omnidata_auth"

    # --- connection pools --------------------------------------------------------
    pool_size: int = Field(default=5, ge=1, le=50)
    pool_max_overflow: int = Field(default=5, ge=0, le=50)
    pool_recycle_seconds: int = 1800

    # --- migration / ingestion tuning -------------------------------------------
    migration_batch_size: int = Field(default=200, ge=1, le=1000)
    migration_stale_seconds: int = Field(default=300, ge=10)
    publish_batch_size: int = Field(default=200, ge=1, le=1000)
    worker_batch_size: int = Field(default=50, ge=1, le=500)
    worker_max_attempts: int = Field(default=5, ge=1, le=20)
    worker_stale_seconds: int = Field(default=300, ge=10)
    worker_poll_seconds: float = Field(default=2.0, gt=0)

    @property
    def mssql_url(self) -> URL:
        return URL.create(
            "mssql+pymssql",
            username=self.mssql_user,
            password=self.mssql_password.get_secret_value(),
            host=self.mssql_host,
            port=self.mssql_port,
            database=self.mssql_database,
        )

    @property
    def postgres_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        )

    @property
    def mysql_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
