"""应用配置：全部项可用 APP_ 前缀环境变量 / backend/.env 覆盖。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → parents[2] = backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=_BACKEND_ROOT / ".env", extra="ignore"
    )

    host: str = "127.0.0.1"
    port: int = 8420
    open_browser: bool = True
    data_dir: Path = _BACKEND_ROOT / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def courses_dir(self) -> Path:
        return self.data_dir / "courses"


settings = AppConfig()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.courses_dir.mkdir(parents=True, exist_ok=True)
