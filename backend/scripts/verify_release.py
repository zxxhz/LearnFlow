# -*- coding: utf-8 -*-
"""发布后确定性核验（替代"靠子代理自述发版成功"）。

用法：python scripts/verify_release.py <version> [--local] [--latest <路径>]
  --local  只核验本地 latest.json 与本地安装包（dryRun 模式用）
  默认追加远程核验：标签已推送 / Release 存在 / 资产齐全 / 远程 latest.json
  （notes ≥100 字符，直接堵死 v0.4.64 缺日志类事故）/ 下载 URL 可达且大小一致 /
  发布 sha256 与本地 exe 重算一致。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
NSIS_DIR = REPO / "desktop/src-tauri/target/release/bundle/nsis"
API = "https://api.github.com"
OWNER, REPO_NAME = "zxxhz", "LearnFlow"
MIN_REMOTE_NOTES = 100
MIN_LOCAL_NOTES = 30


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--latest", default="")
    args = ap.parse_args()

    version = args.version.strip()
    tag = f"v{version}"
    exe = NSIS_DIR / f"LearnFlow_{version}_x64-setup.exe"
    latest_path = Path(args.latest) if args.latest else Path(tempfile.gettempdir()) / f"latest-v{version}.json"

    failures: list[str] = []
    passed: list[str] = []

    def check(ok: bool, msg: str) -> None:
        (passed if ok else failures).append(msg)
        print(("  ✅ " if ok else "  ❌ ") + msg)

    print(f"=== 发布核验 v{version}（{'--local' if args.local else 'local + remote'}） ===")

    # 本地元数据
    if not latest_path.exists():
        check(False, f"latest.json 不存在：{latest_path}")
        meta = None
    else:
        meta = json.loads(latest_path.read_text(encoding="utf-8"))
        check(meta.get("version") == version, f"latest.json version = {meta.get('version')!r}")
        notes = (meta.get("notes") or "").strip()
        check(len(notes) >= MIN_LOCAL_NOTES, f"notes 长度 {len(notes)} ≥ {MIN_LOCAL_NOTES}")
        plat = (meta.get("platforms") or {}).get("windows-x86_64") or {}
        check(bool(plat.get("signature")), "signature 字段非空")
        local_sha = sha256_of(exe) if exe.exists() else ""
        check(bool(exe.exists()), f"本地安装包存在：{exe.name}")
        if plat.get("sha256") and local_sha:
            check(plat["sha256"] == local_sha, "发布 sha256 与本地安装包重算一致")

    if not args.local:
        # 远程标签
        ls = run_git(["-c", "http.sslbackend=openssl", "ls-remote", "--tags", f"https://github.com/{OWNER}/{REPO_NAME}.git", f"refs/tags/{tag}"])
        tag_ok = (ls.returncode == 0 and bool(ls.stdout.strip()))
        if not tag_ok:
            try:
                r_tag = httpx.get(f"{API}/repos/{OWNER}/{REPO_NAME}/git/ref/tags/{tag}", headers={"User-Agent": "LearnFlow-Verify"}, timeout=15)
                tag_ok = (r_tag.status_code == 200)
            except Exception:
                pass
        check(tag_ok, f"标签 {tag} 已推送至 origin")

        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            # Release 存在
            r = client.get(f"{API}/repos/{OWNER}/{REPO_NAME}/releases/tags/{tag}")
            check(r.status_code == 200, f"GitHub Release {tag} 存在（HTTP {r.status_code}）")
            if r.status_code == 200:
                release = r.json()
                names = [a["name"] for a in release.get("assets", [])]
                check(f"LearnFlow_{version}_x64-setup.exe" in names, f"资产含安装包：{names}")
                check("latest.json" in names, "资产含 latest.json")

            def fetch_with_mirror_fallback(url: str, is_head: bool = False):
                try:
                    return client.head(url) if is_head else client.get(url)
                except Exception:
                    # 国内直连 github.com:443 波动超时，通过主流镜像测速通道复核
                    mirror_url = f"https://gh-proxy.com/{url}"
                    return client.head(mirror_url) if is_head else client.get(mirror_url)

            # 远程 latest.json
            rr = fetch_with_mirror_fallback(
                f"https://github.com/{OWNER}/{REPO_NAME}/releases/download/{tag}/latest.json"
            )
            check(rr.status_code == 200, f"远程 latest.json 可下载（HTTP {rr.status_code}）")
            if rr.status_code == 200:
                remote = rr.json()
                rnotes = (remote.get("notes") or "").strip()
                check(len(rnotes) >= MIN_REMOTE_NOTES, f"远程 notes 长度 {len(rnotes)} ≥ {MIN_REMOTE_NOTES}（缺日志事故防线）")
                rplat = (remote.get("platforms") or {}).get("windows-x86_64") or {}
                check(bool(rplat.get("signature")), "远程 signature 非空")
                expected_url = f"https://github.com/{OWNER}/{REPO_NAME}/releases/download/{tag}/LearnFlow_{version}_x64-setup.exe"
                check(rplat.get("url") == expected_url, f"远程下载 URL 正确：{rplat.get('url')}")
                if meta and (meta.get("platforms") or {}).get("windows-x86_64", {}).get("sha256"):
                    check(
                        rplat.get("sha256") == meta["platforms"]["windows-x86_64"]["sha256"],
                        "远程与本地 latest.json 的 sha256 一致（上传未损坏）",
                    )
                # 下载 URL 可达 + 大小一致
                if exe.exists():
                    head = fetch_with_mirror_fallback(expected_url, is_head=True)
                    size = head.headers.get("content-length")
                    check(
                        head.status_code == 200 and size and int(size) == exe.stat().st_size,
                        f"安装包下载 URL HTTP {head.status_code}，Content-Length={size} 与本地 {exe.stat().st_size} 一致",
                    )

    if failures:
        print(f"❌ 核验未通过（{len(failures)} 项失败）：")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"✅ 发布核验全部通过（{len(passed)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
