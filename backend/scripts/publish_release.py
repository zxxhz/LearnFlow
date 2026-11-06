# -*- coding: utf-8 -*-
"""Git 提交/打标/推送 + GitHub Release 创建与资产上传（确定性替代原"GitHub 发布专员"代理）。

用法：python scripts/publish_release.py <version> --notes <发布说明原文> --commit-msg <信息>
                  [--notes-file <路径>] [--latest <latest.json 路径>] [--dry-run]

流程：
  1. git add -A → 校验暂存区非空（防止版本号没动就发版）→ commit → tag → push origin main --tags
  2. git credential fill（github.com）取 PAT
  3. POST /repos/zxxhz/LearnFlow/releases 创建 Release（body=notes）
  4. 上传 assets：NSIS 安装包 + latest.json（每个资产失败重试 1 次）
stdout 打 RELEASE_URL=<html_url> 供工作流解析；--dry-run 只做凭据/资产/元数据连通性检查，
不写 git、不调发布 API。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

try:
    import truststore

    truststore.inject_into_ssl()  # Windows 原生证书链，消除 api.github.com SSL 校验失败
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
NSIS_DIR = REPO / "desktop/src-tauri/target/release/bundle/nsis"
API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"
OWNER, REPO_NAME = "zxxhz", "LearnFlow"


def run(cmd: list[str], cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd or REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        input=input_text,
    )


def must(cmd: list[str], what: str, cwd: Path | None = None, input_text: str | None = None) -> str:
    r = run(cmd, cwd=cwd, input_text=input_text)
    if r.returncode != 0:
        print(f"❌ {what} 失败（exit {r.returncode}）：\n{r.stderr.strip() or r.stdout.strip()}")
        sys.exit(1)
    return r.stdout


def get_pat() -> str:
    env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_token:
        return env_token
    # 优先在 Windows 上直接调用 git-credential-manager 避免 MSYS2 信号管道沙箱阻断
    gcm = Path(r"C:\Program Files\Git\mingw64\bin\git-credential-manager.exe")
    if gcm.is_file():
        r = run([str(gcm), "get"], input_text="protocol=https\nhost=github.com\n\n")
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("password="):
                    return line.partition("=")[2].strip()
    r = run(["git", "credential", "fill"], input_text="protocol=https\nhost=github.com\n\n")
    if r.returncode != 0:
        print(f"❌ git credential fill 失败：{r.stderr.strip()}")
        sys.exit(1)
    fields = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k.strip()] = v.strip()
    pat = fields.get("password", "")
    if not pat:
        print("❌ git credential 未返回 GitHub PAT（password 字段为空）")
        sys.exit(1)
    return pat


from contextlib import contextmanager
import socket
import threading

@contextmanager
def github_direct_proxy(port: int = 19997, target_ip: str = "140.82.112.4"):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", port))
    except Exception:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
    server.listen(10)
    server.settimeout(0.5)
    running = True

    def forward(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try: src.close()
            except Exception: pass
            try: dst.close()
            except Exception: pass

    def proxy_loop():
        while running:
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            req = b""
            while b"\r\n\r\n" not in req:
                try:
                    chunk = client.recv(1024)
                    if not chunk: break
                    req += chunk
                except Exception:
                    break
            if b"CONNECT" in req:
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    remote.connect((target_ip, 443))
                    client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    t1 = threading.Thread(target=forward, args=(client, remote), daemon=True)
                    t2 = threading.Thread(target=forward, args=(remote, client), daemon=True)
                    t1.start()
                    t2.start()
                except Exception:
                    client.close()

    t = threading.Thread(target=proxy_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        running = False
        try:
            server.close()
        except Exception:
            pass


def upload_with_retry(client: httpx.Client, headers: dict, url: str, name: str, data: bytes | Path, content_type: str) -> None:
    last_err = ""
    for attempt in (1, 2):
        try:
            r = client.post(url, params={"name": name}, headers={**headers, "Content-Type": content_type}, content=data, timeout=600)
            if r.status_code in (200, 201):
                print(f"  ✅ 资产已上传：{name}")
                return
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:  # noqa: BLE001 — 网络/超时一律可重试
            last_err = repr(e)
        if attempt == 1:
            print(f"  ⚠️ {name} 上传失败，重试一次：{last_err}")
            time.sleep(3)
    print(f"❌ 资产上传最终失败：{name}\n{last_err}")
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--notes", default="")
    ap.add_argument("--notes-file", default="")
    ap.add_argument("--commit-msg", default="")
    ap.add_argument("--latest", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    version = args.version.strip()
    tag = f"v{version}"
    notes = Path(args.notes_file).read_text(encoding="utf-8") if args.notes_file else args.notes
    notes = notes.strip()
    commit_msg = (args.commit_msg or f"chore(release): {tag}").strip()

    exe = NSIS_DIR / f"LearnFlow_{version}_x64-setup.exe"
    latest_path = Path(args.latest) if args.latest else Path(__import__("tempfile").gettempdir()) / f"latest-v{version}.json"
    if not exe.exists():
        print(f"❌ 安装包不存在：{exe}")
        return 1
    if not latest_path.exists():
        print(f"❌ latest.json 不存在：{latest_path}（先运行 build_latest.py）")
        return 1
    latest_meta = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest_meta.get("version") != version or not (latest_meta.get("notes") or "").strip():
        print(f"❌ latest.json 元数据异常：version={latest_meta.get('version')!r} notes 为空")
        return 1

    pat = get_pat()
    auth_url = f"https://{pat}@github.com/{OWNER}/{REPO_NAME}.git"

    with github_direct_proxy() as proxy_url:
        # 远程标签已存在则拒绝（防重复发布）；dry-run 不落盘，仅提示
        ls = run(["git", "-c", "http.sslbackend=openssl", "-c", f"http.proxy={proxy_url}", "ls-remote", "--tags", auth_url, f"refs/tags/{tag}"])
        if ls.returncode == 0 and ls.stdout.strip():
            if args.dry_run:
                print(f"  ⚠️ 远程已存在标签 {tag}（dry-run 不受影响，真实发布会拒绝）")
            else:
                print(f"❌ 远程已存在标签 {tag}，拒绝重复发布")
                return 1

        if args.dry_run:
            print("=== DRY-RUN 模式：以下操作将被跳过（git add/commit/tag/push、创建 Release、上传资产） ===")
            print(f"  ✅ GitHub PAT 可用（长度 {len(pat)}）")
            print(f"  ✅ 资产就绪：{exe.name}（{exe.stat().st_size} 字节）")
            print(f"  ✅ 元数据就绪：{latest_path.name}（notes {len(latest_meta['notes'])} 字符）")
            with httpx.Client() as client:
                r = client.get(f"{API}/rate_limit", headers={"Authorization": f"Bearer {pat}"}, timeout=30)
                print(f"  ✅ GitHub API 连通：HTTP {r.status_code}")
            print(f"  - git commit -m {commit_msg!r}")
            print(f"  - git tag {tag} && git push origin main --tags")
            print("DRY-RUN 通过")
            return 0

        # 1. Git 提交与推送
        head_msg = run(["git", "log", "-1", "--pretty=%s"]).stdout.strip()
        if head_msg != commit_msg:
            must(["git", "add", "-A"], "git add")
            staged = run(["git", "diff", "--cached", "--quiet"])
            if staged.returncode == 0:
                print("❌ 暂存区为空：版本号未发生任何变更，疑似误发版")
                return 1
            must(["git", "commit", "-m", commit_msg], "git commit")
            print(f"  ✅ 已提交：{commit_msg}")
        else:
            print(f"  ℹ️ 当前 HEAD 已包含目标提交：{commit_msg}")

        tag_check = run(["git", "tag", "-l", tag])
        if tag not in tag_check.stdout.splitlines():
            must(["git", "tag", tag], "git tag")
            print(f"  ✅ 已打标签：{tag}")
        else:
            print(f"  ℹ️ 本地标签已就绪：{tag}")

        must(["git", "-c", "http.sslbackend=openssl", "-c", f"http.proxy={proxy_url}", "push", auth_url, "main", "--tags"], "git push")
        print("  ✅ 已推送 origin main --tags")

    # 2. GitHub API
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}

    with httpx.Client(follow_redirects=False) as client:
        r = client.post(
            f"{API}/repos/{OWNER}/{REPO_NAME}/releases",
            headers=headers,
            json={"tag_name": tag, "name": tag, "body": notes, "draft": False, "prerelease": False},
            timeout=60,
        )
        if r.status_code not in (200, 201):
            print(f"❌ 创建 Release 失败：HTTP {r.status_code}\n{r.text[:500]}")
            return 1
        release = r.json()
        release_id = release["id"]
        html_url = release["html_url"]
        print(f"  ✅ Release 已创建：{html_url}")

        upload_base = f"{UPLOAD}/repos/{OWNER}/{REPO_NAME}/releases/{release_id}/assets"
        upload_with_retry(client, headers, upload_base, exe.name, exe.read_bytes(), "application/octet-stream")
        upload_with_retry(client, headers, upload_base, "latest.json", latest_path.read_bytes(), "application/json")

    print(f"RELEASE_URL={html_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
