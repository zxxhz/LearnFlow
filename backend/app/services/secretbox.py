# -*- coding: utf-8 -*-
"""LLM api_key 落盘加密（Windows DPAPI，用户级）。

背景（v0.5.2 体检 P1 实证）：执行沙箱与宿主同用户运行，sqlite 明文存储的 api_key
可被沙箱内代码（含被诱导粘贴的"测试代码"）直接读走。将 api_key 以 DPAPICryptProtectData
加密落盘后，同用户的其他进程虽仍能解密，但拦截了「沙箱 stdout 直接打印明文」这条
最低门槛的泄露路径，并把密钥暴露面收敛到 DPAPI 语义（绑定 Windows 用户 + 可选审计）。

格式：密文以 `dpapi:` 前缀 + base64 存储于 app_settings.llm 的 api_key 字段
（主配置与三个场景槽位）。解密失败（换 Windows 用户/系统重装）按未配置处理，
引导用户重新填写；非 Windows 平台与历史明文值原样透传（平滑迁移，读路径兼容两态）。
"""
import base64
import logging
import os

logger = logging.getLogger(__name__)

_PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), "LearnFlow", None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    if not ok:
        raise OSError(f"DPAPI {'CryptProtectData' if protect else 'CryptUnprotectData'} failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def encrypt_secret(value: str) -> str:
    """明文 → `dpapi:` 密文。空值/已加密值/非 Windows 平台原样返回。"""
    if not value or value.startswith(_PREFIX) or os.name != "nt":
        return value
    try:
        blob = _dpapi_transform(value.encode("utf-8"), protect=True)
        return _PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception:  # noqa: BLE001
        logger.warning("api_key DPAPI 加密失败，回落明文存储", exc_info=True)
        return value


def decrypt_secret(value: str) -> str:
    """`dpapi:` 密文 → 明文。明文值原样返回；解密失败按未配置处理（空串）。"""
    if not value or not value.startswith(_PREFIX):
        return value
    try:
        blob = base64.b64decode(value[len(_PREFIX):])
        return _dpapi_transform(blob, protect=False).decode("utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("api_key DPAPI 解密失败（可能因更换 Windows 用户/系统），按未配置处理")
        return ""


def decrypt_llm_config(cfg: dict) -> dict:
    """就地解密 LLM 配置 JSON 中的主 api_key 与三个场景槽位 api_key（返回同一 dict）。"""
    if not isinstance(cfg, dict):
        return cfg
    if cfg.get("api_key"):
        cfg["api_key"] = decrypt_secret(str(cfg["api_key"]))
    scenes = cfg.get("scenes")
    if isinstance(scenes, dict):
        for scene_cfg in scenes.values():
            if isinstance(scene_cfg, dict) and scene_cfg.get("api_key"):
                scene_cfg["api_key"] = decrypt_secret(str(scene_cfg["api_key"]))
    return cfg


def encrypt_llm_config(cfg: dict) -> dict:
    """就地加密 LLM 配置 JSON 中的主 api_key 与三个场景槽位 api_key（落库前调用）。"""
    if not isinstance(cfg, dict):
        return cfg
    if cfg.get("api_key"):
        cfg["api_key"] = encrypt_secret(str(cfg["api_key"]))
    scenes = cfg.get("scenes")
    if isinstance(scenes, dict):
        for scene_cfg in scenes.values():
            if isinstance(scene_cfg, dict) and scene_cfg.get("api_key"):
                scene_cfg["api_key"] = encrypt_secret(str(scene_cfg["api_key"]))
    return cfg
