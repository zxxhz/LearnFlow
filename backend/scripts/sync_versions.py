# -*- coding: utf-8 -*-
"""八处版本号同步：config.py / pyproject.toml / 两个 package.json / tauri.conf.json /
Cargo.toml / sw.js CACHE_NAME / Cargo.lock learnflow-desktop。

用法：python scripts/sync_versions.py <version> [--dry]
  --dry  只校验各文件模式命中并打印将替换的内容，不写盘。

原则：按字节读写（不经过通用换行转换，保持 CRLF/LF 原样）；任何目标未恰好命中
一次旧版本模式即失败退出（避免静默半同步）；写盘后回读断言旧串已消失。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

V = r"0\.\d+\.\d+"  # 现行版本号模式（只处理 X.Y.Z，避免误替换依赖版本）


def targets(version: str) -> list[tuple[Path, str, str, str]]:
    """(文件, 命中模式, re.sub 替换模板, 说明)。"""
    q = re.escape(version)
    return [
        (
            REPO / "backend/app/core/config.py",
            rf'APP_VERSION = "{V}"',
            f'APP_VERSION = "{version}"',
            "后端 APP_VERSION",
        ),
        (
            REPO / "backend/pyproject.toml",
            rf'(?m)^version = "{V}"',
            f'version = "{version}"',
            "backend pyproject",
        ),
        (
            REPO / "desktop/package.json",
            rf'"version": "{V}",',
            f'"version": "{version}",',
            "desktop package.json",
        ),
        (
            REPO / "frontend/package.json",
            rf'"version": "{V}",',
            f'"version": "{version}",',
            "frontend package.json",
        ),
        (
            REPO / "desktop/src-tauri/tauri.conf.json",
            rf'"version": "{V}",',
            f'"version": "{version}",',
            "tauri.conf.json",
        ),
        (
            REPO / "desktop/src-tauri/Cargo.toml",
            rf'(?m)^version = "{V}"',
            f'version = "{version}"',
            "Cargo.toml [package]",
        ),
        (
            REPO / "frontend/public/sw.js",
            rf'CACHE_NAME = "learnflow-v{V}"',
            f'CACHE_NAME = "learnflow-v{version}"',
            "sw.js CACHE_NAME",
        ),
        (
            REPO / "desktop/src-tauri/Cargo.lock",
            rf'(\[\[package\]\]\r?\nname = "learnflow-desktop"\r?\nversion = "){V}(")',
            rf"\g<1>{version}\g<2>",
            "Cargo.lock learnflow-desktop",
        ),
    ]


def read_raw(path: Path) -> str:
    """按字节读文本：不做通用换行转换，保留 CRLF/LF 原样。"""
    return path.read_bytes().decode("utf-8")


def write_raw(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: sync_versions.py <version> [--dry]")
        return 2
    version = sys.argv[1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"❌ 版本号格式不合法：{version!r}")
        return 1
    dry = "--dry" in sys.argv[2:]

    # 第一遍：全量校验——每个文件必须恰好命中一次旧版本模式
    plans: list[tuple[Path, str, re.Pattern[str], str, str]] = []  # (path, label, rx, repl, old_match)
    problems: list[str] = []
    for path, pattern, replacement, label in targets(version):
        if not path.exists():
            problems.append(f"{label}: 文件不存在 {path}")
            continue
        rx = re.compile(pattern)
        hits = rx.findall(read_raw(path))
        if len(hits) != 1:
            problems.append(f"{label}: 期望恰好 1 处旧版本模式，实际命中 {len(hits)} 处（{path}）")
            continue
        old_match = rx.search(read_raw(path)).group(0)  # type: ignore[union-attr]
        plans.append((path, label, rx, replacement, old_match))

    if problems:
        print("❌ 版本同步中止（模式校验失败）：")
        for p in problems:
            print(f"  - {p}")
        return 1

    if dry:
        print(f"✅ --dry 校验通过，将把 {len(plans)} 处版本号替换为 {version}：")
        for _, label, _, _, old in plans:
            shown = old.replace("\r", "").replace("\n", "⏎")
            if len(shown) > 60:
                shown = shown[:57] + "..."
            print(f"  - {label}: {shown}")
        return 0

    # 第二遍：应用替换并回读断言（字节级一致，避免任何模糊子串误判）
    for path, label, rx, replacement, old_match in plans:
        text = read_raw(path)
        expected = rx.sub(replacement, text, count=1)
        if expected == text:
            print(f"❌ {label}: 替换未产生任何变化")
            return 1
        write_raw(path, expected)
        back = read_raw(path)
        if back != expected or old_match in back:
            print(f"❌ {label}: 写入后回读校验失败")
            return 1
        print(f"  ✅ {label}")

    print(f"✅ 八处版本号已同步为 {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
