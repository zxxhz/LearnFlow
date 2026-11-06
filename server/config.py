"""自建云端中转服务端配置。"""
import os
from pathlib import Path
from typing import Literal

def _get_bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "y")


def _get_ai_mode_env() -> str:
    val = os.getenv("AI_MODE", os.getenv("RELAY_AI_MODE", os.getenv("SERVER_AI_MODE", "auto"))).strip().lower()
    if val in ("cloud", "local", "auto"):
        return val
    return "auto"


def _resolve_default_static_dir() -> Path:
    env_static = os.getenv("STATIC_DIR")
    if env_static:
        return Path(env_static).resolve()

    base_dir = Path(__file__).resolve().parent.parent
    frontend_dist = base_dir / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        return frontend_dist

    backend_static = base_dir / "backend" / "app" / "static"
    if backend_static.exists():
        return backend_static

    local_static = Path(__file__).resolve().parent / "static"
    return local_static


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

        host: str = os.getenv("SERVER_HOST", "0.0.0.0")
        port: int = int(os.getenv("SERVER_PORT", os.getenv("RELAY_PORT", os.getenv("PORT", "8421"))))
        relay_auth_required: bool = _get_bool_env("RELAY_AUTH_REQUIRED", False)
        relay_server_token: str = os.getenv("RELAY_SERVER_TOKEN", os.getenv("RELAY_TOKEN", os.getenv("SERVER_TOKEN", ""))).strip()
        static_dir: Path = _resolve_default_static_dir()
        data_dir: Path = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent / "data"))).resolve()

        # AI 执行模式: "cloud" (走云端服务端LLM) | "local" (反向代理走本地Worker) | "auto" (本地在线走本地，离线平滑降级走云端)
        ai_mode: str = _get_ai_mode_env()

        # 服务端内置 LLM 配置（用于云端模式）
        server_llm_base_url: str = os.getenv(
            "SERVER_LLM_BASE_URL",
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        ).rstrip("/")
        server_llm_api_key: str = os.getenv("SERVER_LLM_API_KEY", os.getenv("LLM_API_KEY", "")).strip()
        server_llm_model: str = os.getenv("SERVER_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini")).strip()

        def is_auth_enabled(self) -> bool:
            """判断是否开启鉴权。
            若 relay_auth_required 为 False 且 Token 为空，则完全跳过鉴权（开放访问）。
            若 relay_auth_required 为 True 或 Token 非空，则开启鉴权。
            """
            if not self.relay_auth_required and not self.relay_server_token:
                return False
            return True

        def is_server_llm_configured(self) -> bool:
            """判断服务端大模型是否已配置有效参数。"""
            if self.server_llm_api_key:
                return True
            # 本地容器如 Ollama / vLLM 无需 key
            if any(h in self.server_llm_base_url for h in ("localhost", "127.0.0.1", ":11434", "ollama", "vllm")):
                return True
            return False

except ImportError:
    from pydantic import BaseModel, Field

    class Settings(BaseModel):
        host: str = Field(default_factory=lambda: os.getenv("SERVER_HOST", "0.0.0.0"))
        port: int = Field(
            default_factory=lambda: int(os.getenv("SERVER_PORT", os.getenv("RELAY_PORT", os.getenv("PORT", "8421"))))
        )
        relay_auth_required: bool = Field(
            default_factory=lambda: _get_bool_env("RELAY_AUTH_REQUIRED", False)
        )
        relay_server_token: str = Field(
            default_factory=lambda: os.getenv("RELAY_SERVER_TOKEN", os.getenv("RELAY_TOKEN", os.getenv("SERVER_TOKEN", ""))).strip()
        )
        static_dir: Path = Field(default_factory=_resolve_default_static_dir)
        data_dir: Path = Field(
            default_factory=lambda: Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent / "data"))).resolve()
        )

        ai_mode: str = Field(default_factory=_get_ai_mode_env)
        server_llm_base_url: str = Field(
            default_factory=lambda: os.getenv(
                "SERVER_LLM_BASE_URL",
                os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            ).rstrip("/")
        )
        server_llm_api_key: str = Field(
            default_factory=lambda: os.getenv("SERVER_LLM_API_KEY", os.getenv("LLM_API_KEY", "")).strip()
        )
        server_llm_model: str = Field(
            default_factory=lambda: os.getenv("SERVER_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini")).strip()
        )

        def is_auth_enabled(self) -> bool:
            """判断是否开启鉴权。
            若 relay_auth_required 为 False 且 Token 为空，则完全跳过鉴权（开放访问）。
            若 relay_auth_required 为 True 或 Token 非空，则开启鉴权。
            """
            if not self.relay_auth_required and not self.relay_server_token:
                return False
            return True

        def is_server_llm_configured(self) -> bool:
            """判断服务端大模型是否已配置有效参数。"""
            if self.server_llm_api_key:
                return True
            if any(h in self.server_llm_base_url for h in ("localhost", "127.0.0.1", ":11434", "ollama", "vllm")):
                return True
            return False


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
