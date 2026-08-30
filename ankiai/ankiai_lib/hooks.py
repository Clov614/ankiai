"""AnkAI 主控制器：注册 hooks，串起 选中 → 右键菜单 → TTS / LLM → 面板。"""

from __future__ import annotations

import base64

from aqt import gui_hooks
from aqt.qt import QMessageBox
from aqt.utils import tooltip

from . import menu as menu_mod
from . import selection, tts
from .panel import ExplainPanel

SEL_PREFIX = "ankiai:sel:"


class AnkAI:
    def __init__(self, mw):
        self.mw = mw
        self.selection = ""
        self.side = "question"  # 复习界面当前展示的是题目还是答案
        self.panel: ExplainPanel | None = None
        self._tts_busy = False

    # ---------- 安装 ----------

    def install(self) -> None:
        from .util import set_debug_logging

        gui_hooks.webview_will_show_context_menu.append(self._on_context_menu)
        gui_hooks.webview_did_receive_js_message.append(self._on_js_message)
        gui_hooks.reviewer_did_show_question.append(lambda card: self._on_show("question"))
        gui_hooks.reviewer_did_show_answer.append(lambda card: self._on_show("answer"))
        gui_hooks.top_toolbar_did_init_links.append(self._on_top_toolbar_links)
        gui_hooks.theme_did_change.append(self._on_theme_change)
        action = self.mw.form.menuTools.addAction("AnkAI 解释面板")
        action.triggered.connect(self.show_panel_toggle)
        action = self.mw.form.menuTools.addAction("AnkAI 设置…")
        action.triggered.connect(self.open_settings)
        self._register_shortcuts()
        set_debug_logging(bool(self.get_config().get("ui", {}).get("debug_log", False)))

    def _on_theme_change(self) -> None:
        if self.panel is not None:
            self.panel._apply_theme()

    def _on_top_toolbar_links(self, links, toolbar) -> None:
        """顶部工具栏常驻按钮：固定入口，方便随时唤出面板。"""
        links.append(
            toolbar.create_link(
                "ankai_toggle",
                "🤖 AnkAI",
                self.show_panel_toggle,
                tip="AnkAI 解释面板（显示 / 隐藏）",
                id="nav-ankai",
            )
        )

    def _register_shortcuts(self) -> None:
        """快捷键：解释/朗读依赖复习界面的划选缓存，限定在复习状态触发；
        面板开关全局可用。"""
        from aqt.qt import QKeySequence, QShortcut

        for keys, slot in (
            ("Ctrl+Shift+A", self._shortcut_explain),
            ("Ctrl+Shift+S", self._shortcut_speak),
            ("Ctrl+Shift+P", self.show_panel_toggle),
        ):
            shortcut = QShortcut(QKeySequence(keys), self.mw)
            shortcut.activated.connect(slot)
        from .util import log

        log("shortcuts registered")

    def _shortcut_explain(self) -> None:
        if getattr(self.mw, "state", "") != "review":
            tooltip("AnkAI：AI 解释要在复习界面划选卡片文字后用")
            return
        self.explain(None)

    def _shortcut_speak(self) -> None:
        if getattr(self.mw, "state", "") != "review":
            tooltip("AnkAI：朗读要在复习界面使用（读所选或整卡）")
            return
        self.speak("")

    def _on_show(self, side: str) -> None:
        self.side = side
        if side == "question":
            self.selection = ""  # 换卡后旧选中失效
        reviewer = getattr(self.mw, "reviewer", None)
        if reviewer is not None:
            selection.install(reviewer.web)
        from .util import log

        log(f"on_show side={side} js_installed")

    def _on_js_message(self, handled, message, context):
        if not isinstance(message, str) or not message.startswith(SEL_PREFIX):
            return handled
        payload = message[len(SEL_PREFIX):]
        try:
            self.selection = base64.b64decode(payload).decode("utf-8", "replace")
        except Exception:
            self.selection = ""
        from .util import log

        log(f"sel cached chars={len(self.selection)}")
        return (True, None)

    def _on_context_menu(self, webview, menu) -> None:
        try:
            menu_mod.add_actions(self, webview, menu)
        except Exception:
            from .util import log_exc

            log_exc("context_menu")

    # ---------- 动作 ----------

    def explain(self, fmt: str | None) -> None:
        from .util import log, log_exc

        try:
            text = (self.selection or "").strip()
            log(f"explain fmt={fmt} sel_chars={len(text)}")
            if not text:
                tooltip("AnkAI：请先划选卡片上的文字")
                return
            if fmt is None:
                fmt = self.get_config()["explain"].get("default_format", "mirra")
            log("explain building panel")
            panel = self._ensure_panel()
            log("explain panel ok, showing")
            panel.show()
            panel.raise_()
            panel.activateWindow()
            panel.start_explain(text, fmt)
            log("explain started")
        except Exception:
            log_exc("explain")

    def speak(self, sel_text: str) -> None:
        from .util import log, log_exc

        try:
            if self._tts_busy:
                tooltip("AnkAI：正在合成语音，请稍候…")
                return
            text = (sel_text or "").strip() or menu_mod.visible_card_text(self)
            log(f"speak sel_chars={len((sel_text or '').strip())} total_chars={len(text)}")
            if not text:
                tooltip("AnkAI：没有可朗读的文本")
                return
            cfg = self.get_config()
            voice = tts.voice_for(text, cfg)
            log(f"speak voice={voice}")
            self._tts_busy = True
            tooltip(f"AnkAI：正在合成语音 {voice} …")

            def work():
                from .util import log as _log

                _log("tts work start")
                try:
                    path = tts.synth(text, cfg)
                    _log(f"synth ok {path.name}")
                except tts.EdgeTTSMissing as exc:
                    _log("synth edge-tts missing")
                    self.run_on_main(lambda p=exc.python: self._offer_install(p))
                except Exception as exc:
                    _log(f"synth fail {exc}")
                    self.run_on_main(lambda e=exc: tooltip(f"AnkAI 朗读失败：{e}"))
                else:
                    self.run_on_main(lambda p=path: self._play(p))
                finally:
                    self._tts_busy = False

            log("tts dispatching background")
            self.run_in_background(work)
            log("tts dispatched")
        except Exception:
            log_exc("speak")

    def _play(self, path) -> None:
        try:
            tts.play(path)
        except Exception as exc:
            tooltip(f"AnkAI 播放失败：{exc}")

    def _offer_install(self, python: str) -> None:
        ret = QMessageBox.question(
            self.mw,
            "AnkAI",
            "朗读功能需要免费的 edge-tts 库（调用微软 Edge 语音，无需 API key）。\n"
            f"检测到它尚未安装到：\n{python}\n\n"
            "现在自动安装吗？（约需十几秒，之后即可直接朗读）",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        tooltip("AnkAI：正在安装 edge-tts…")

        def work():
            try:
                tts.install_edge_tts(python)
            except Exception as exc:
                self.run_on_main(lambda e=exc: tooltip(f"AnkAI：安装失败 {e}"))
            else:
                self.run_on_main(lambda: tooltip("AnkAI：edge-tts 安装完成，请再次右键朗读"))

        self.run_in_background(work)

    def show_panel_toggle(self) -> None:
        """显示/隐藏解释面板；隐藏只是收起，对话保留，可随时唤回。
        面板按需创建：进入 Anki 后不划词也能直接打开面板查看/回溯历史。"""
        panel = self._ensure_panel()
        if panel.isVisible():
            panel.hide()
        else:
            panel.show()
            panel.raise_()
            panel.activateWindow()

    def open_settings(self) -> None:
        from .util import log, log_exc

        try:
            log("open_settings")
            from .settings import SettingsDialog

            dlg = SettingsDialog(self.mw)
            log("settings dialog built")
            dlg.exec()
            log("settings closed")
        except Exception:
            log_exc("open_settings")

    # ---------- 基础设施 ----------

    def _ensure_panel(self) -> ExplainPanel:
        if self.panel is None:
            self.panel = ExplainPanel(self)
        return self.panel

    def get_config(self) -> dict:
        from .util import get_config_safe

        return get_config_safe()

    def run_in_background(self, fn) -> None:
        # 我们的任务（LLM 网络 / edge-tts 子进程）都不碰 collection；
        # 默认的 uses_collection=True 是单线程串行执行器，LLM 长流会饿死 TTS
        self.mw.taskman.run_in_background(fn, uses_collection=False)

    def run_on_main(self, fn) -> None:
        self.mw.taskman.run_on_main(fn)
