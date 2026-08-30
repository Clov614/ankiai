"""打发布包：生成可上传 AnkiWeb / 手动安装的 .ankiaddon 文件。

用法：
    python package.py          # 输出 dist/ankiai-<版本>.ankiaddon

.ankiaddon 就是一个 zip，但要求：
- 插件文件直接放在压缩包根部（不带顶层文件夹，否则 AnkiWeb 拒收）
- 不含 __pycache__ / *.pyc / user_files / meta.json
- manifest.json 必须含 package 与 name 字段
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
DIST = SRC.parent / "dist"

# 进包内容：白名单式列出，天然排除 user_files / __pycache__ / deploy.py 等开发产物
ROOT_FILES = ["__init__.py", "manifest.json", "config.json", "config.md", "README.md", "LICENSE"]
LIB_DIR = "ankiai_lib"


def build() -> Path:
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    for required in ("package", "name"):
        if not manifest.get(required):
            raise SystemExit(f"manifest.json 缺少必需字段 {required!r}")
    version = manifest.get("human_version", "0.0.0")
    out = DIST / f"ankiai-{version}.ankiaddon"

    entries: list[tuple[str, Path]] = []
    for name in ROOT_FILES:
        p = SRC / name
        if not p.exists():
            raise SystemExit(f"缺少文件：{name}")
        entries.append((name, p))
    for p in sorted((SRC / LIB_DIR).glob("*.py")):
        entries.append((f"{LIB_DIR}/{p.name}", p))

    DIST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, p in entries:
            zf.write(p, arcname)
    print(f"已生成 {out}（{out.stat().st_size / 1024:.1f} KB，{len(entries)} 个文件）")
    return out


if __name__ == "__main__":
    build()
