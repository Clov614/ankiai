"""把插件复制到 Anki 的 addons21 目录。

用法：
    python deploy.py            # 复制/更新（保留 meta.json 与 user_files）
    python deploy.py --open     # 复制后打开 addons21 目录
    python deploy.py --force    # Anki 正在运行时也强制部署（不推荐）
部署后重启 Anki 生效（或在 工具>插件 里禁用再启用本插件）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
ADDON_NAME = "ankiai"
KEEP = {"meta.json", "user_files"}
SKIP_COPY = {"deploy.py", "package.py", "README.md", "docs", "__pycache__", ".git", "user_files"}


def addons21_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("未找到 APPDATA 环境变量，请在 Windows 上运行")
    return Path(appdata) / "Anki2" / "addons21" / ADDON_NAME


def _decode_output(data: bytes) -> str:
    """子进程输出解码：tasklist 输出跟随系统 ANSI 代码页（中文系统是 GBK）。

    不能用 text=True：在中文 Windows 上 tasklist 的 GBK 字节按 UTF-8 解码
    会让读取线程抛异常，导致探测静默失效。
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", "replace")


def anki_running() -> bool:
    """Anki 运行中时插件文件被锁定，先删后拷会留下半部署状态。"""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq anki.exe"],
            capture_output=True,
            timeout=10,
            **_tasklist_no_window(),
        )
    except Exception:
        return False  # 探测失败时不阻塞部署
    return "anki.exe" in _decode_output(out.stdout or b"").lower()


def _tasklist_no_window() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def deploy() -> Path:
    dst = addons21_dir()
    if dst.exists():
        for item in dst.iterdir():
            if item.name in KEEP:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    dst.mkdir(parents=True, exist_ok=True)

    for item in SRC.iterdir():
        if item.name in SKIP_COPY or item.name.startswith("."):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)

    print(f"已部署 {SRC}")
    print(f"  -> {dst}")
    print("重启 Anki 后生效。")
    return dst


if __name__ == "__main__":
    if "--force" not in sys.argv and anki_running():
        sys.exit(
            "检测到 Anki 正在运行：插件文件可能被占用，部署会失败或留下残缺文件。\n"
            "请先关闭 Anki 再运行本脚本；确要继续请用 python deploy.py --force"
        )
    target = deploy()
    if "--open" in sys.argv:
        subprocess.Popen(["explorer", str(target)])
