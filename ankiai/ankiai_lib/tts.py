"""Edge TTS：子进程调用系统 Python 的 edge-tts 库（免费微软语音，无需 key）。

合成结果按 文本+voice+rate 的 sha1 缓存为 mp3；播放走 aqt.sound.av_player。
阻塞函数（synth/install）都必须在后台线程调用。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

from .langdetect import detect_lang
from .util import subprocess_no_window_kwargs as _no_window_kwargs

MAX_TTS_CHARS = 3000
RETRY_TIMES = 3


class TTSError(Exception):
    pass


class EdgeTTSMissing(Exception):
    """系统 Python 里没有 edge-tts 库。"""

    def __init__(self, python: str):
        super().__init__("edge-tts 未安装")
        self.python = python


def _cache_dir() -> Path:
    # add-on 根目录下的 user_files 会在插件更新时被 Anki 保留
    base = Path(__file__).resolve().parent.parent / "user_files" / "tts"
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_python(configured: str = "") -> str:
    if configured:
        return configured
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return found
    raise TTSError("找不到系统 Python，请在 AnkAI 设置里填写 python 完整路径")


def voice_for(text: str, cfg: dict) -> str:
    lang = detect_lang(text)
    t = cfg.get("tts", {})
    # 兜底值与 DEFAULTS 的 fallback_voice 保持一致
    return t.get(f"voice_{lang}") or t.get("fallback_voice") or "en-GB-LibbyNeural"


def synth(text: str, cfg: dict) -> Path:
    """合成（或命中缓存）并返回 mp3 路径。"""
    text = " ".join(text.split())[:MAX_TTS_CHARS]
    if not text:
        raise TTSError("没有可朗读的文本")

    t = cfg.get("tts", {})
    voice = voice_for(text, cfg)
    rate = t.get("rate", "+0%")
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    path = _cache_dir() / f"ankiai_{key}.mp3"
    if path.exists() and path.stat().st_size > 0:
        return path

    tmp = path.with_name(path.name + ".part")
    python = resolve_python(t.get("python_cmd", ""))
    err = ""
    for attempt in range(RETRY_TIMES):
        try:
            proc = subprocess.run(
                [
                    python, "-m", "edge_tts",
                    "--voice", voice,
                    "--text", text,
                    "--rate", rate,
                    "--write-media", str(tmp),
                ],
                capture_output=True,
                timeout=120,
                **_no_window_kwargs(),
            )
        except FileNotFoundError:
            raise TTSError(f"无法启动 Python：{python}") from None
        except subprocess.TimeoutExpired:
            err = "edge-tts 超时"
        else:
            err = proc.stderr.decode("utf-8", "replace")
            if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(path)
                return path
            if "No module named" in err and "edge_tts" in err:
                _cleanup(tmp)
                raise EdgeTTSMissing(python) from None
        _cleanup(tmp)
        if attempt < RETRY_TIMES - 1:
            time.sleep(2**attempt)
    raise TTSError(f"edge-tts 合成失败：{err.strip()[:300]}")


def install_edge_tts(python: str) -> None:
    """同步安装 edge-tts 到指定 Python（后台线程调用）。"""
    proc = subprocess.run(
        [python, "-m", "pip", "install", "--upgrade", "edge-tts"],
        capture_output=True,
        timeout=300,
        **_no_window_kwargs(),
    )
    if proc.returncode != 0:
        raise TTSError(
            "安装 edge-tts 失败：" + proc.stderr.decode("utf-8", "replace")[:400]
        )


def play(path: Path) -> None:
    from aqt.sound import av_player

    av_player.play_file(str(path))


def list_voices(python_cmd: str = "") -> list[str]:
    """列出本机 edge-tts 可用的全部音色（后台线程调用）。"""
    python = resolve_python(python_cmd)
    try:
        proc = subprocess.run(
            [python, "-m", "edge_tts", "--list-voices"],
            capture_output=True,
            timeout=60,
            **_no_window_kwargs(),
        )
    except FileNotFoundError:
        raise TTSError(f"无法启动 Python：{python}") from None
    except subprocess.TimeoutExpired:
        raise TTSError("获取音色列表超时") from None
    if proc.returncode != 0:
        raise TTSError(proc.stderr.decode("utf-8", "replace")[:200])
    voices = re.findall(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural\b", proc.stdout.decode("utf-8", "replace"), flags=re.M)
    return sorted(set(voices))


def _cleanup(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
