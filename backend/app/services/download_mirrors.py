"""下载源测速与智能路由服务。

支持针对 GitHub 官方直连与多个国内主流加速镜像源进行并发测速，
提供「哪个快用哪个（自动择优）」策略，并允许用户在设置中自定义与即时测试。
"""
import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings as app_settings

logger = logging.getLogger(__name__)

# 主流国内 GitHub 加速镜像预设
MIRROR_PRESETS: list[dict[str, Any]] = [
    {
        "id": "official",
        "name": "GitHub 官方 (直连)",
        "prefix": "",
        "desc": "直接连接 GitHub 官方节点，无第三方中转",
        "is_custom": False,
    },
    {
        "id": "gh_proxy_com",
        "name": "GH-Proxy",
        "prefix": "https://gh-proxy.com/",
        "desc": "国内稳定 GitHub 文件代理加速通道",
        "is_custom": False,
    },
    {
        "id": "ghfast_top",
        "name": "GHFast",
        "prefix": "https://ghfast.top/",
        "desc": "国内多线路加速代理节点",
        "is_custom": False,
    },
    {
        "id": "ghproxy_net",
        "name": "GHProxy",
        "prefix": "https://ghproxy.net/",
        "desc": "经典常用 GitHub 镜像代理",
        "is_custom": False,
    },
    {
        "id": "moeyy",
        "name": "Moeyy 镜像",
        "prefix": "https://github.moeyy.xyz/",
        "desc": "公益免流 GitHub 镜像加速通道",
        "is_custom": False,
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


def _custom_mirrors_path() -> Path:
    return app_settings.data_dir / "custom_mirrors.json"


def load_custom_mirrors() -> list[dict[str, Any]]:
    """读取用户添加的自定义镜像源列表。"""
    p = _custom_mirrors_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.warning("读取自定义镜像配置失败: %s", e)
    return []


def save_custom_mirrors(mirrors: list[dict[str, Any]]) -> None:
    """持久化保存用户自定义镜像源列表。"""
    try:
        app_settings.data_dir.mkdir(parents=True, exist_ok=True)
        _custom_mirrors_path().write_text(
            json.dumps(mirrors, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("保存自定义镜像配置失败: %s", e)


def get_all_mirrors() -> list[dict[str, Any]]:
    """获取所有可用镜像源（系统预设 + 用户自定义）。"""
    customs = load_custom_mirrors()
    for c in customs:
        c["is_custom"] = True
    return [dict(p) for p in MIRROR_PRESETS] + customs


def _get_preset(mirror_id: str) -> dict[str, Any] | None:
    for m in get_all_mirrors():
        if m["id"] == mirror_id:
            return m
    return None


def add_custom_mirror(name: str, prefix: str, desc: str = "") -> dict[str, Any]:
    """添加用户自定义镜像源。

    prefix 规范化：必须以 http:// 或 https:// 开头，末尾保证包含 '/'。
    """
    name = (name or "").strip()
    prefix = (prefix or "").strip()
    if not name:
        raise ValueError("镜像名称不能为空")
    if not (prefix.startswith("http://") or prefix.startswith("https://")):
        raise ValueError("镜像地址前缀必须以 http:// 或 https:// 开头")
    if not prefix.endswith("/"):
        prefix += "/"

    customs = load_custom_mirrors()
    # 检查是否已存在相同前缀
    for c in customs:
        if c.get("prefix") == prefix:
            raise ValueError(f"已存在相同前缀的自定义镜像「{c.get('name')}」")

    mirror_id = f"custom_{secrets.token_hex(4)}"
    item = {
        "id": mirror_id,
        "name": name,
        "prefix": prefix,
        "desc": desc.strip() or "用户自定义 GitHub 加速镜像源",
        "is_custom": True,
    }
    customs.append(item)
    save_custom_mirrors(customs)

    # 若当前未测速过缓存中只有旧列表，重置结果缓存让新源即刻呈现
    if _cache.get("results"):
        _cache["results"].append({
            "id": mirror_id,
            "name": name,
            "prefix": prefix,
            "desc": item["desc"],
            "is_custom": True,
            "ok": None,
            "latency_ms": None,
            "error": None,
        })
    return get_mirrors_status()


def remove_custom_mirror(mirror_id: str) -> dict[str, Any]:
    """删除指定的自定义镜像源。"""
    customs = load_custom_mirrors()
    new_customs = [c for c in customs if c.get("id") != mirror_id]
    if len(new_customs) == len(customs):
        raise ValueError("未找到指定的自定义镜像源")

    save_custom_mirrors(new_customs)

    # 如果当前手动锁定的正是该被删除的镜像，自动恢复为 auto
    if _cache.get("selected_id") == mirror_id:
        _cache["selected_id"] = "auto"
        _cache["mode"] = "auto"
    if _cache.get("fastest_id") == mirror_id:
        _cache["fastest_id"] = "official"

    if _cache.get("results"):
        _cache["results"] = [r for r in _cache["results"] if r.get("id") != mirror_id]

    return get_mirrors_status()


async def _probe_mirror(client: httpx.AsyncClient, item: dict[str, Any], test_target: str) -> dict[str, Any]:
    prefix = item["prefix"]
    url = f"{prefix}{test_target}" if prefix else test_target
    t0 = time.time()
    is_custom = bool(item.get("is_custom", False))
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
                "is_custom": is_custom,
                "ok": True,
                "latency_ms": round(dt, 1),
                "error": None,
            }
        return {
            "id": item["id"],
            "name": item["name"],
            "prefix": item["prefix"],
            "desc": item["desc"],
            "is_custom": is_custom,
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
            "is_custom": is_custom,
            "ok": False,
            "latency_ms": round(dt, 1),
            "error": err_msg,
        }


async def run_speed_test(test_target: str | None = None) -> dict[str, Any]:
    """并发测试所有镜像源（含自定义源）的延迟并更新最优源。"""
    repo = (app_settings.github_repo or DEFAULT_TEST_REPO).strip("/")
    if not test_target:
        test_target = f"https://github.com/{repo}/releases/latest/download/latest.json"

    all_mirrors = get_all_mirrors()
    headers = {"User-Agent": "LearnFlow-SpeedTest/1.0"}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        tasks = [_probe_mirror(client, item, test_target) for item in all_mirrors]
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


def get_active_mirror() -> dict[str, Any]:
    """返回当前生效的下载源信息。"""
    mode = _cache.get("mode", "auto")
    selected_id = _cache.get("selected_id", "auto")
    fastest_id = _cache.get("fastest_id", "official")

    chosen_id = fastest_id if mode == "auto" or selected_id == "auto" else selected_id
    preset = _get_preset(chosen_id) or _get_preset("official")
    return preset or get_all_mirrors()[0]


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
    all_mirrors = get_all_mirrors()
    if results:
        prefixes = []
        for r in results:
            if r.get("prefix") is not None and r["prefix"] not in prefixes:
                prefixes.append(r["prefix"])
        for p in all_mirrors:
            if p["prefix"] not in prefixes:
                prefixes.append(p["prefix"])
        return prefixes
    return [p["prefix"] for p in all_mirrors]


def set_mirror_selection(mode: str, selected_id: str) -> dict[str, Any]:
    """设置下载源选择策略：'auto'（自动使用最快）或 'manual' + 指定 id。"""
    if mode not in ("auto", "manual"):
        mode = "auto"
    _cache["mode"] = mode
    if mode == "manual":
        # 若未指定具体镜像 ID 或误传了 auto，则以当前最快源或官方源作为初始锁定项
        if not selected_id or selected_id == "auto":
            selected_id = _cache.get("fastest_id") or "official"
        _cache["selected_id"] = selected_id
    else:
        _cache["selected_id"] = "auto"
    return get_mirrors_status()


def get_mirrors_status() -> dict[str, Any]:
    """获取当前测速状态及配置信息。"""
    active = get_active_mirror()
    all_mirrors = get_all_mirrors()
    all_ids = {m["id"]: m for m in all_mirrors}

    cached_results = _cache.get("results") or []
    cached_map = {r["id"]: r for r in cached_results}

    # 合并最新镜像列表（保证动态增删自定义镜像后状态同步）
    merged_results = []
    for m in all_mirrors:
        mid = m["id"]
        if mid in cached_map:
            item = dict(cached_map[mid])
            item["name"] = m["name"]
            item["prefix"] = m["prefix"]
            item["desc"] = m["desc"]
            item["is_custom"] = bool(m.get("is_custom", False))
            merged_results.append(item)
        else:
            merged_results.append({
                "id": m["id"],
                "name": m["name"],
                "prefix": m["prefix"],
                "desc": m["desc"],
                "is_custom": bool(m.get("is_custom", False)),
                "ok": None,
                "latency_ms": None,
                "error": None,
            })

    # 若曾测过速，按测速结果排序（成功在前，延迟从小到大）
    if _cache.get("tested_at", 0.0) > 0:
        merged_results.sort(key=lambda x: (x.get("ok") is not True, x.get("latency_ms") or 999999))

    return {
        "tested_at": _cache.get("tested_at", 0.0),
        "mode": _cache.get("mode", "auto"),
        "selected_id": _cache.get("selected_id", "auto"),
        "fastest_id": _cache.get("fastest_id", "official"),
        "active_mirror": active,
        "results": merged_results,
    }
