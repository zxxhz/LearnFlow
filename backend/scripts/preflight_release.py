# -*- coding: utf-8 -*-
"""发版预检：版本号格式 / 标签冲突 / 工作树清洁。

用法：python scripts/preflight_release.py <version>
退出码 0 = 全部通过；非 0 = 有阻塞项（错误信息逐条打印）。

供 release-learnflow 工作流在版本同步前以 world.run 确定性门禁调用。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 会话自有目录（工作流/计划文件等）允许在发版时随 git add -A 一并提交
ALLOWED_DIRTY_PREFIX = ".zcode/"


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: preflight_release.py <version>")
        return 2
    version = sys.argv[1].strip()
    tag = f"v{version}"

    errors: list[str] = []

    # 1. 语义化版本格式
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append(f"版本号格式不合法：{version!r}（应为 X.Y.Z 三段数字）")

    # 2a. 本地标签不存在
    local_tag = run_git(["rev-parse", "-q", "--verify", f"refs/tags/{tag}"])
    if local_tag.returncode == 0:
        errors.append(f"本地标签 {tag} 已存在（{local_tag.stdout.strip()}），疑似重复发版")

    # 2b. 远程标签不存在
    remote_tags = run_git(["ls-remote", "--tags", "origin", f"refs/tags/{tag}"])
    if remote_tags.returncode == 0:
        if remote_tags.stdout.strip():
            errors.append(f"远程 origin 已存在标签 {tag}，禁止重复发布")
    else:
        # git ls-remote 失败（Windows 沙箱或环境无直接凭据），回落经 GitHub API 验证
        try:
            import httpx
            r = httpx.get(
                f"https://api.github.com/repos/zxxhz/LearnFlow/git/ref/tags/{tag}",
                headers={"User-Agent": "LearnFlow-Preflight"},
                timeout=15,
            )
            if r.status_code == 200:
                errors.append(f"远程 GitHub 已存在标签 {tag}，禁止重复发布")
            elif r.status_code not in (404,):
                errors.append(f"GitHub API 查询远程标签返回异常状态码 HTTP {r.status_code}")
        except Exception as e:
            errors.append(f"查询远程标签失败（git: {remote_tags.stderr.strip()}; api: {e}）")

    # 3. 工作树清洁（.zcode/ 下的会话文件豁免）
    status = run_git(["status", "--porcelain"])
    if status.returncode != 0:
        errors.append(f"git status 失败：{status.stderr.strip()}")
    else:
        offenders: list[str] = []
        for line in status.stdout.splitlines():
            if not line.strip():
                continue
            # porcelain 格式："XY path" / "XY orig -> path"，带空格路径会被引号包裹
            path = line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path.startswith(ALLOWED_DIRTY_PREFIX):
                continue
            offenders.append(line)
        if offenders:
            errors.append(
                "工作树存在未提交变更（git add -A 会把它们扫进发版提交），请先处理：\n  "
                + "\n  ".join(offenders[:20])
                + ("\n  …" if len(offenders) > 20 else "")
            )

    if errors:
        print("❌ 发布预检未通过：")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"✅ 发布预检通过：v{version} 格式合法、本地/远程标签可用、工作树干净（.zcode/ 会话文件已豁免）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
