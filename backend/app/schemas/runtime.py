"""运行环境（代码沙箱工具链）接口模型。"""
from typing import Literal

from pydantic import BaseModel

RuntimeSource = Literal["bundled", "managed", "system", "none"]


class RuntimeComponent(BaseModel):
    installed: bool
    source: RuntimeSource = "none"
    path: str = ""
    version: str = ""


class RuntimeStatusOut(BaseModel):
    python: RuntimeComponent
    cpp: RuntimeComponent
    platform: str
    installable: bool
    toolchains_dir: str


class InstallStateOut(BaseModel):
    state: Literal["idle", "downloading", "extracting", "done", "error"]
    percent: float = 0.0
    message: str = ""
    error: str | None = None
    log: list[str] = []


class InstallStatusOut(BaseModel):
    components: dict[str, InstallStateOut]
    active: Literal["python", "cpp"] | None = None


class InstallRequest(BaseModel):
    component: Literal["python", "cpp"]
