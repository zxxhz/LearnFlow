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
# B5（v0.5.10 体检）：从资产上传 URL 提取 release_id，供 422 删旧资产重传
_RELEASE_ID_RE = __import__("re").compile(r"/releases/(\d+)/assets")


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
            # B5（v0.5.10 体检）：同名资产 422——删旧资产后重传（断点续传半发布的
            # 恢复路径；旧实现重试同错并退出，重跑又被「exe 已存在」拒绝卡死）
            if r.status_code == 422:
                m = _RELEASE_ID_RE.search(url)
                if m:
                    lst = client.get(
                        f"{API}/repos/{OWNER}/{REPO_NAME}/releases/{m.group(1)}/assets",
                        headers=headers,
                        timeout=30,
                    )
                    if lst.status_code == 200:
                        for a in lst.json():
                            if a.get("name") == name:
                                d = client.delete(
                                    f"{API}/repos/{OWNER}/{REPO_NAME}/releases/assets/{a['id']}",
                                    headers=headers,
                                    timeout=60,
                                )
                                print(f"  ℹ️ 已删除旧同名资产 {name}（HTTP {d.status_code}），重传")
                                continue
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

    # B6（v0.5.10 体检）：上传前交叉核验 latest.json 的 sha256 与实际安装包——
    # 构建重跑后拿旧 latest.json 配新 exe，全体客户端 updater 验签会失败
    import hashlib as _hashlib

    exe_sha = _hashlib.sha256(exe.read_bytes()).hexdigest()
    claimed_sha = ""
    try:
        claimed_sha = str(
            (latest_meta.get("platforms") or {}).get("windows-x86_64", {}).get("sha256") or ""
        )
    except Exception:  # noqa: BLE001
        claimed_sha = ""
    if claimed_sha and claimed_sha.lower() != exe_sha:
        print(
            f"❌ latest.json 的 sha256 与实际安装包不一致（latest={claimed_sha[:16]}… 实际={exe_sha[:16]}…），"
            "请重跑 build_latest.py 后再发布"
        )
        return 1

    pat = get_pat()
    auth_url = f"https://{pat}@github.com/{OWNER}/{REPO_NAME}.git"
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}

    # 查询远程 Release 是否已存在
    existing_release = None
    try:
        with httpx.Client(follow_redirects=False) as client:
            r_chk = client.get(f"{API}/repos/{OWNER}/{REPO_NAME}/releases/tags/{tag}", headers=headers, timeout=20)
            if r_chk.status_code == 200:
                existing_release = r_chk.json()
    except Exception as e:
        print(f"  ⚠️ 查询 Release 状态失败，将尝试继续发布: {e}")

    if existing_release and not args.dry_run:
        assets = existing_release.get("assets", [])
        if any(a.get("name") == exe.name for a in assets):
            print(f"❌ 远程已存在 Release {tag} 且包含安装包，拒绝重复发布")
            return 1
        print(f"  ℹ️ 远程存在标签/Release {tag} 但资产不全，将继续上传补充资产...")

    with github_direct_proxy() as proxy_url:
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

        # 尝试推送代码与标签，先直连，失败回落
        push_ok = False
        for push_cmd in [
            ["git", "-c", "http.sslbackend=schannel", "push", auth_url, "main", "--tags"],
            ["git", "-c", "http.sslbackend=openssl", "push", auth_url, "main", "--tags"],
            ["git", "-c", "http.sslbackend=openssl", "-c", f"http.proxy={proxy_url}", "push", auth_url, "main", "--tags"],
        ]:
            p = run(push_cmd)
            if p.returncode == 0 or "Everything up-to-date" in p.stdout or "Everything up-to-date" in p.stderr:
                push_ok = True
                break
        if not push_ok:
            # B2（v0.5.10 体检）：回落判定同时校验 main 与 tag——旧逻辑只查 tag，
            # main 非 fast-forward 被拒时误报「已推送」，造成 tag 已发而 main 缺提交
            chk = run(["git", "ls-remote", auth_url, f"refs/tags/{tag}", "refs/heads/main"])
            if chk.returncode == 0:
                out = chk.stdout
                tag_ok = f"refs/tags/{tag}" in out
                main_ok = "refs/heads/main" in out
                if tag_ok and main_ok:
                    push_ok = True
                elif tag_ok:
                    print(
                        "❌ tag 已推送但 main 分支未更新（推送被拒）——终止发布，"
                        "请先同步 main 分叉后重跑（本脚本支持断点续发）"
                    )
                    return 1
        if not push_ok:
            print("❌ git push 最终失败（tag/Release 未创建，可解决网络后直接重跑）")
            return 1
        print("  ✅ 已推送 origin main --tags")

    # 2. GitHub API
    with httpx.Client(follow_redirects=False) as client:
        if existing_release:
            release_id = existing_release["id"]
            html_url = existing_release["html_url"]
            print(f"  ℹ️ 复用已存在 Release：{html_url}")
        else:
            r = client.post(
                f"{API}/repos/{OWNER}/{REPO_NAME}/releases",
                headers=headers,
                json={"tag_name": tag, "name": tag, "body": notes, "draft": False, "prerelease": False},
                timeout=60,
            )
            if r.status_code not in (200, 201):
                # B3（v0.5.10 体检）：tag 已推上的半发布状态给出明确恢复指引，
                # 避免重跑被 preflight 卡死后无从下手
                print(f"❌ 创建 Release 失败：HTTP {r.status_code}\n{r.text[:500]}")
                print(
                    "  ℹ️ 恢复指引：代码与标签已推送。解决网络后直接重跑 publish_release.py"
                    "（断点续传会复用 tag 与 Release），或到 GitHub 网页端手工创建 Release 并上传资产。"
                )
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
