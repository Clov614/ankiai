"""配置读写。默认值在包根 config.json 里同步维护一份（Anki 用它生成配置界面）。

本模块只在此处 import aqt，纯逻辑部分保持无 aqt 依赖，便于独立测试。
"""

from __future__ import annotations

import copy
import subprocess
import sys

ADDON_ID = "ankiai"


def subprocess_no_window_kwargs() -> dict:
    """GUI 进程起子进程时不弹控制台黑框（Windows 双保险）。

    CREATE_NO_WINDOW 对常规控制台程序足够；STARTUPINFO(SW_HIDE) 兜底
    .cmd shim / 应用别名等仍会闪窗的启动路径。
    """
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }

DEFAULTS: dict = {
    "llm": {
        "provider": "claude-cli",  # claude-cli | openai | anthropic
        "claude_cmd": "claude",
        "claude_model": "",
        "claude_timeout": 300,
        "openai_base_url": "https://api.deepseek.com/v1",
        "openai_api_key": "",
        "openai_model": "deepseek-chat",
        "anthropic_api_key": "",
        "anthropic_model": "claude-sonnet-4-5",
        "temperature": 0.7,
        "max_tokens": 3072,  # 推理模型的思考也计入该额度；太大易导致超长输出
    },
    "tts": {
        "python_cmd": "",
        "rate": "+0%",
        "voice_en": "en-GB-LibbyNeural",
        "voice_ja": "ja-JP-NanamiNeural",
        "voice_zh": "zh-CN-XiaoxiaoNeural",
        "voice_ko": "ko-KR-SunHiNeural",
        "voice_ru": "ru-RU-SvetlanaNeural",
        "fallback_voice": "en-GB-LibbyNeural",
    },
    "explain": {
        "default_format": "mirra",  # mirra | sentence
        "custom_prompt": "",
    },
    "cards": {
        "model_name": "EnWords",  # 制卡用的笔记类型（缺失时自动创建）
        "default_deck": "",  # 上次成功制卡的牌组；留空用当前牌组
        "default_tags": "ankiai",
        "attach_word_audio": True,  # 制卡时用 edge-tts 附单词发音
    },
    "ui": {"panel_width": 560, "panel_height": 640, "debug_log": False},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def get_config() -> dict:
    from aqt import mw

    user_cfg = mw.addonManager.getConfig(ADDON_ID) or {}
    return deep_merge(DEFAULTS, user_cfg)


def write_config(cfg: dict) -> None:
    from aqt import mw

    mw.addonManager.writeConfig(ADDON_ID, cfg)


# 调试日志默认关闭（每次划选/翻卡都写文件太吵）；由启动与设置界面按配置打开
_debug_log_enabled = False
_LOG_ROTATE_BYTES = 1_000_000


def set_debug_logging(enabled: bool) -> None:
    global _debug_log_enabled
    _debug_log_enabled = bool(enabled)


def log(msg: str) -> None:
    """轻量调试日志：user_files/ankiai.log。默认关闭，仅 debug_log=true 时写。"""
    if not _debug_log_enabled:
        return
    _write_log(msg)


def log_exc(prefix: str) -> None:
    """异常日志：不受 debug_log 开关限制——错误必须留痕，且发生频率低。"""
    import traceback

    _write_log(f"{prefix} 异常：\n{traceback.format_exc()}")


def _write_log(msg: str) -> None:
    try:
        import time
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent / "user_files"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "ankiai.log"
        # 超过 1MB 轮转成 .old，避免无上限增长
        if path.exists() and path.stat().st_size > _LOG_ROTATE_BYTES:
            path.replace(path.with_name("ankiai.log.old"))
        stamp = time.strftime("%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


def get_config_safe() -> dict:
    """getConfig 失败时回退默认值，并把错误写日志。"""
    try:
        from aqt import mw

        user_cfg = mw.addonManager.getConfig(ADDON_ID)
        return deep_merge(DEFAULTS, user_cfg or {})
    except Exception:
        log_exc("getConfig")
        return deep_merge(DEFAULTS, {})
