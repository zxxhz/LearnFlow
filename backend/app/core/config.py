"""应用配置：全部项可用 APP_ 前缀环境变量 / .env 覆盖。"""
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 应用版本（更新检查的唯一版本源；发布时与 tauri.conf.json / package.json 一同 bump，见 PRD 实现备注 15）
APP_VERSION = "0.4.26"



# GitHub 仓库（owner/repo）：设置页字段为空时的默认值；发布到 GitHub 后在 .env 里配置
# APP_GITHUB_REPO=your-name/learnflow 即可启用启动时更新检查
DEFAULT_GITHUB_REPO = "zxxhz/LearnFlow"

# backend/app/core/config.py → parents[2] = backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# PyInstaller 打包（onedir）时 __file__ 指向临时解包目录：可写基准改为 exe 所在目录
_FROZEN = getattr(sys, "frozen", False)
_BASE_DIR = Path(sys.executable).resolve().parent if _FROZEN else _BACKEND_ROOT


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=_BASE_DIR / ".env", extra="ignore"
    )

    host: str = "0.0.0.0"
    port: int = 8420
    open_browser: bool = True
    data_dir: Path = _BASE_DIR / "data"
    github_repo: str = DEFAULT_GITHUB_REPO

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def courses_dir(self) -> Path:
        return self.data_dir / "courses"

    @property
    def toolchains_dir(self) -> Path:
        """便携工具链根目录：软件安装目录下（打包版 = 安装目录/backend/toolchains，
        开发版 = backend/toolchains）。刻意不放进 data_dir：工具链体积大且是缓存性质，
        不应混进「复制即备份」的数据目录。"""
        return _BASE_DIR / "toolchains"


settings = AppConfig()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.courses_dir.mkdir(parents=True, exist_ok=True)
