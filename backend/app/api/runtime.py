"""运行环境 API：代码沙箱的 Python / C++ 工具链检测与一键便携安装（设置页 + 代码块提示共用）。"""
from fastapi import APIRouter, HTTPException

from app.schemas.runtime import (
    InstallRequest,
    InstallStatusOut,
    RuntimeStatusOut,
)
from app.services.execution import toolchain

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/status", response_model=RuntimeStatusOut)
def status():
    """当前 Python / C++ 运行环境检测（source：bundled 内置 / managed 应用内 / system 系统 / none 缺失）。

    用同步 def：内部要起子进程做版本探测（杀软首扫时可到秒级），交给 FastAPI
    线程池执行，避免阻塞事件循环拖住全部 API。
    """
    return toolchain.runtime_status()


@router.get("/install/status", response_model=InstallStatusOut)
async def install_status():
    """安装进度（前端 1s 轮询；active 为正在安装的组件，全部空闲时为 null）。"""
    return toolchain.get_install_status()


@router.post("/install", response_model=InstallStatusOut)
async def install(body: InstallRequest):
    """启动便携安装（后台线程执行，立即返回当前进度；重复触发返回 409）。"""
    try:
        toolchain.start_install(body.component)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return toolchain.get_install_status()
