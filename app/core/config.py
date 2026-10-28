from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="OBSINF_",
        extra="ignore",
    )

    env: str = "local"
    database_url: SecretStr
    data_dir: Path = PROJECT_ROOT / "data"
    local_dev_mode: bool = False

    # Límites de recepción. Se comprueban mientras leemos los archivos.
    max_files_per_batch: int = 10
    max_file_size_mb: int = 20
    max_batch_size_mb: int = 100

    # Ventana máxima permitida para consultar observaciones.
    max_query_days: int = 31


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    if settings.env != "local" and settings.local_dev_mode:
        raise ValueError(
            "El modo local de desarrollo solo se permite con OBSINF_ENV=local"
        )

    if not settings.data_dir.is_absolute():
        settings.data_dir = PROJECT_ROOT / settings.data_dir

    return settings