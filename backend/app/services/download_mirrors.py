"""下载源测速与智能路由服务。

支持针对 GitHub 官方直连与多个国内主流加速镜像源进行并发测速，
提供「哪个快用哪个（自动择优）」策略，并允许用户在设置中自定义与即时测试。
"""
import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.config import settings as app_settings

logger = logging.getLogger(__name__)

# 主流国内 GitHub 加速镜像预设
MIRROR_PRESETS: list[dict[str, str]] = [
    {
        "id": "official",
        "name": "GitHub 官方 (直连)",
        "prefix": "",
        "desc": "直接连接 GitHub 官方节点，无第三方中转",
    },
    {
        "id": "gh_proxy_com",
        "name": "GH-Proxy",
        "prefix": "https://gh-proxy.com/",
        "desc": "国内稳定 GitHub 文件代理加速通道",
    },
    {
        "id": "ghfast_top",
        "name": "GHFast",
        "prefix": "https://ghfast.top/",
        "desc": "国内多线路加速代理节点",
    },
    {
        "id": "ghproxy_net",
        "name": "GHProxy",
        "prefix": "https://ghproxy.net/",
        "desc": "经典常用 GitHub 镜像代理",
    },
    {
        "id": "moeyy",
        "name": "Moeyy 镜像",
        "prefix": "https://github.moeyy.xyz/",
        "desc": "公益免流 GitHub 镜像加速通道",
    },
]

# 状态缓存
_cache: dict[str, Any] = {
    "tested_at": 0.0,
    "results": [],
    "mode": "auto",  # 'auto' | 'manual'
    "selected_id": "auto",
    "fastest_id": "official",
}

DEFAULT_TEST_REPO = "zxxhz/LearnFlow"


def _get_preset(mirror_id: str) -> dict[str, str] | None:
    for m in MIRROR_PRESETS:
        if m["id"] == mirror_id:
            return m
    return None


async def _probe_mirror(client: httpx.AsyncClient, item: dict[str, str], test_target: str) -> dict[str, Any]:
    prefix = item["prefix"]
    url = f"{prefix}{test_target}" if prefix else test_target
    t0 = time.time()
    try:
        # 使用轻量 Range 请求或 GET 小包，超时限制 4.5s
        resp = await client.get(url, timeout=4.5)
        dt = (time.time() - t0) * 1000
        if resp.status_code in (200, 206):
            return {
                "id": item["id"],
                "name": item["name"],
                "prefix": item["prefix"],
                "desc": item["desc"],
                "ok": True,
                "latency_ms": round(dt, 1),
                "error": None,
            }
        return {
            "id": item["id"],
            "name": item["name"],
            "prefix": item["prefix"],
            "desc": item["desc"],
            "ok": False,
            "latency_ms": round(dt, 1),
            "error": f"HTTP {resp.status_code}",
        }
    except Exception as e:
        dt = (time.time() - t0) * 1000
        err_msg = str(e)
        if "timeout" in err_msg.lower():
            err_msg = "连接超时 (Timeout)"
        elif "ssl" in err_msg.lower():
            err_msg = "SSL 握手失败"
        else:
            err_msg = err_msg[:60]
        return {
            "id": item["id"],
            "name": item["name"],
            "prefix": item["prefix"],
            "desc": item["desc"],
            "ok": False,
            "latency_ms": round(dt, 1),
            "error": err_msg,
        }


async def run_speed_test(test_target: str | None = None) -> dict[str, Any]:
    """并发测试所有镜像源的延迟并更新最优源。"""
    repo = (app_settings.github_repo or DEFAULT_TEST_REPO).strip("/")
    if not test_target:
        test_target = f"https://github.com/{repo}/releases/latest/download/latest.json"

    headers = {"User-Agent": "LearnFlow-SpeedTest/1.0"}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        tasks = [_probe_mirror(client, item, test_target) for item in MIRROR_PRESETS]
        results = await asyncio.gather(*tasks)

    # 排序：成功在前，且延迟从低到高排列
    sorted_results = sorted(results, key=lambda x: (not x["ok"], x.get("latency_ms", 999999)))

    fastest_id = "official"
    for r in sorted_results:
        if r["ok"]:
            fastest_id = r["id"]
            break

    _cache["tested_at"] = time.time()
    _cache["results"] = sorted_results
    _cache["fastest_id"] = fastest_id

    logger.info("下载源测速完成，最快源: %s (%s)", fastest_id, _get_preset(fastest_id))
    return get_mirrors_status()


def get_active_mirror() -> dict[str, str]:
    """返回当前生效的下载源信息。"""
    mode = _cache.get("mode", "auto")
    selected_id = _cache.get("selected_id", "auto")
    fastest_id = _cache.get("fastest_id", "official")

    chosen_id = fastest_id if mode == "auto" or selected_id == "auto" else selected_id
    preset = _get_preset(chosen_id) or _get_preset("official")
    return preset or MIRROR_PRESETS[0]


def get_active_mirror_prefix() -> str:
    """获取当前生效镜像的前缀，若为直连则返回空字符串。"""
    return get_active_mirror().get("prefix", "")


def apply_mirror(raw_url: str) -> str:
    """将一个标准 GitHub URL 改写为当前生效镜像的加速 URL。"""
    if not raw_url or not raw_url.startswith("https://github.com/"):
        return raw_url
    prefix = get_active_mirror_prefix()
    return f"{prefix}{raw_url}" if prefix else raw_url


def get_ordered_mirror_prefixes() -> list[str]:
    """获取按当前测速推荐排序的镜像前缀列表，用于重试/竞速链路。"""
    results = _cache.get("results") or []
    if results:
        prefixes = []
        for r in results:
            if r.get("prefix") is not None and r["prefix"] not in prefixes:
                prefixes.append(r["prefix"])
        for p in MIRROR_PRESETS:
            if p["prefix"] not in prefixes:
                prefixes.append(p["prefix"])
        return prefixes
    return [p["prefix"] for p in MIRROR_PRESETS]


def set_mirror_selection(mode: str, selected_id: str) -> dict[str, Any]:
    """设置下载源选择策略：'auto'（自动使用最快）或 'manual' + 指定 id。"""
    if mode not in ("auto", "manual"):
        mode = "auto"
    _cache["mode"] = mode
    _cache["selected_id"] = selected_id if mode == "manual" else "auto"
    return get_mirrors_status()


def get_mirrors_status() -> dict[str, Any]:
    """获取当前测速状态及配置信息。"""
    active = get_active_mirror()
    results = _cache.get("results")
    if not results:
        # 初始未测速状态，提供默认列表
        results = [
            {
                "id": p["id"],
                "name": p["name"],
                "prefix": p["prefix"],
                "desc": p["desc"],
                "ok": None,
                "latency_ms": None,
                "error": None,
            }
            for p in MIRROR_PRESETS
        ]

    return {
        "tested_at": _cache.get("tested_at", 0.0),
        "mode": _cache.get("mode", "auto"),
        "selected_id": _cache.get("selected_id", "auto"),
        "fastest_id": _cache.get("fastest_id", "official"),
        "active_mirror": active,
        "results": results,
    }
