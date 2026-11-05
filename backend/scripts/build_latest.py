# -*- coding: utf-8 -*-
"""生成 Tauri v2 Updater 的 latest.json（确定性替代原"签名与元数据专员"代理）。

用法：python scripts/build_latest.py <version> --notes <发布说明原文>
                  [--notes-file <路径>] [--out <输出路径>]
  --notes / --notes-file 二选一；--out 缺省为 %TEMP%/latest-v<version>.json

校验：安装包与 .sig 必须存在；notes 非空且 ≥30 字符；signature 非空。
输出：写 JSON（UTF-8 无 BOM，ensure_ascii=False），stdout 打 SHA256= / NOTES_LEN= / OUT=
供工作流解析。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NSIS_DIR = REPO / "desktop/src-tauri/target/release/bundle/nsis"
MIN_NOTES = 30


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--notes", default="")
    ap.add_argument("--notes-file", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    version = args.version.strip()
    if not version.replace(".", "").isdigit():
        print(f"❌ 版本号不合法：{version!r}")
        return 1

    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    notes = notes.strip()
    if len(notes) < MIN_NOTES:
        print(f"❌ 发布说明过短（{len(notes)} 字符 < {MIN_NOTES}），latest.json 缺 notes 正是 v0.4.64 事故根因")
        return 1

    exe = NSIS_DIR / f"LearnFlow_{version}_x64-setup.exe"
    sig = NSIS_DIR / f"LearnFlow_{version}_x64-setup.exe.sig"
    if not exe.exists():
        print(f"❌ 安装包不存在：{exe}")
        return 1
    if not sig.exists():
        print(f"❌ 签名文件不存在：{sig}")
        return 1

    signature = sig.read_text(encoding="utf-8").strip()
    if not signature:
        print(f"❌ 签名文件内容为空：{sig}")
        return 1

    digest = sha256_of(exe)
    latest = {
        "version": version,
        "notes": notes,
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            "windows-x86_64": {
                "signature": signature,
                "sha256": digest,
                "url": f"https://github.com/zxxhz/LearnFlow/releases/download/v{version}/{exe.name}",
            }
        },
    }

    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / f"latest-v{version}.json"
    out.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ latest.json 已生成：{out}")
    print(f"SHA256={digest}")
    print(f"NOTES_LEN={len(notes)}")
    print(f"EXE_SIZE={exe.stat().st_size}")
    print(f"OUT={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
