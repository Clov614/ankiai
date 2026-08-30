"""AnkAI —— 卡片划选 AI 解释 + Edge TTS 朗读。

复习界面划选任意文字后右键：AI 解释（米拉四段式 / 例句解析三段式）、
Edge TTS 朗读（多语言自动换声，英文默认英音）。
"""

from __future__ import annotations


def _init() -> None:
    try:
        from aqt import mw

        from .ankiai_lib.hooks import AnkAI

        addon = AnkAI(mw)
        addon.install()
        mw.__ankai = addon
    except Exception:
        # Anki 以 pythonw 运行（无控制台），print/print_exc 会因 sys.stderr 为 None 而二次报错，
        # 必须落到文件日志
        try:
            from .ankiai_lib.util import log_exc

            log_exc("addon init")
        except Exception:
            pass
        try:
            from aqt.utils import showWarning

            showWarning("AnkAI 加载失败，详见 addons21\\ankiai\\user_files\\ankiai.log")
        except Exception:
            pass


_init()
