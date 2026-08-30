"""解释面板：可固定到 Anki 主窗口的 Dock 面板（也可浮动），Markdown 渲染 + 多轮追问。

交互设计（agent 式）：
- 内容区划选后右键：朗读所选 / 让 AI 进一步解释所选 / 引用到输入框 / 复制
- 输入区为多行编辑器，Enter 发送、Shift+Enter 换行，可与内容区拖拽调比例
- 「引用」按钮把内容区当前划选以 blockquote 形式插入输入框
- 生成期间有独立状态栏：转圈动画 + 阶段 + 计时；失败时给出明确原因
- 每轮完成自动存入历史（user_files/history.json），「🕘 历史」可检索并回溯
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy

from aqt.qt import (
    QDockWidget,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QTextBrowser,
    QTextCursor,
    QTimer,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from . import history, llm
from .md2html import md_to_html
from .prompts import FOLLOWUP_RULE, build_messages

_REPAINT_MS = 100
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# 还没有任何对话时的空状态引导（走同一套主题配色）
_EMPTY_HTML = (
    "<h2>🤖 AnkAI 解释面板</h2>"
    "<p>当前还没有对话，可以这样开始：</p>"
    "<ol>"
    "<li>在<b>复习界面</b>划选卡片文字，右键选「🤖 AI 解释」；</li>"
    "<li>点下方「🕘 历史」，回溯任意一次历史对话，可继续追问。</li>"
    "</ol>"
)


class _ContentBrowser(QTextBrowser):
    """内容区：右键提供 朗读/解释所选/引用/复制。"""

    def __init__(self, panel):
        super().__init__()
        self._panel = panel
        self.setOpenExternalLinks(False)

    def contextMenuEvent(self, event) -> None:
        sel = self._selected_text()
        menu = QMenu(self)
        if sel:
            menu.addAction("🔊 朗读所选", lambda: self._panel.speak_selection(sel))
            menu.addAction(
                "🤖 让 AI 进一步解释所选",
                lambda: self._panel.quote_and_ask(sel, "请进一步解释这段内容"),
            )
            menu.addAction("❝ 引用到输入框", lambda: self._panel.quote_selection(sel))
            menu.addSeparator()
            menu.addAction("复制", self.copy)
        menu.addAction("全选", self.selectAll)
        menu.exec(event.globalPos())

    def _selected_text(self) -> str:
        return self.textCursor().selectedText().replace("\u2029", "\n").strip()


class _InputEdit(QPlainTextEdit):
    """多行输入：Enter 发送，Shift+Enter 换行。"""

    def __init__(self, panel):
        super().__init__()
        self._panel = panel
        self.setPlaceholderText("追问…（Enter 发送 · Shift+Enter 换行）")
        self.setMinimumHeight(52)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._panel.send_followup()
            return
        super().keyPressEvent(event)


class HistoryDialog(QDialog):
    """历史列表：可搜索、可多选批量管理（删除/导出）、可回溯。"""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("AnkAI 解释历史")
        self.resize(560, 580)
        self.records: list[dict] = []

        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("搜索划选内容或解释文本…（Ctrl/Shift 可多选）")
        self.filter.textChanged.connect(self.refresh)
        lay.addWidget(self.filter)

        self.listw = QListWidget()
        from aqt.qt import QAbstractItemView

        self.listw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listw.itemDoubleClicked.connect(lambda _item: self.open_selected())
        lay.addWidget(self.listw, 1)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: gray;")
        lay.addWidget(self.count_label)

        btns = QHBoxLayout()
        b_open = QPushButton("回溯打开")
        b_open.clicked.connect(self.open_selected)
        btns.addWidget(b_open)
        b_del = QPushButton("删除所选")
        b_del.clicked.connect(self.delete_selected)
        btns.addWidget(b_del)
        b_export = QPushButton("导出 MD")
        b_export.setToolTip("把所选（未选则导出当前列表全部）导出为 Markdown 文件")
        b_export.clicked.connect(self.export_selected)
        btns.addWidget(b_export)
        b_clear = QPushButton("清空全部")
        b_clear.clicked.connect(self.clear_all)
        btns.addWidget(b_clear)
        btns.addStretch(1)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        btns.addWidget(b_close)
        lay.addLayout(btns)

        self.refresh()

    def refresh(self) -> None:
        kw = self.filter.text().strip().lower()
        self.records = history.load()
        self.listw.clear()
        for r in self.records:
            hay = (r.get("text", "") + " " + r.get("log_md", "")).lower()
            if kw and kw not in hay:
                continue
            fmt = {"mirra": "米拉", "sentence": "例句"}.get(r.get("fmt", ""), r.get("fmt", ""))
            snippet = " ".join(str(r.get("text", "")).split())[:48]
            item = QListWidgetItem(f'{r.get("time", "")} · [{fmt}] {snippet}')
            item.setData(Qt.ItemDataRole.UserRole, r.get("id"))
            self.listw.addItem(item)
        self.count_label.setText(f"共 {len(self.records)} 条 · 当前显示 {self.listw.count()} 条")

    def _selected_records(self) -> list[dict]:
        ids = {i.data(Qt.ItemDataRole.UserRole) for i in self.listw.selectedItems()}
        return [r for r in self.records if r.get("id") in ids]

    def open_selected(self) -> None:
        records = self._selected_records()
        rid = self.listw.currentItem()
        target = None
        if records:
            # 多选时打开当前行所在的那条
            cur_id = rid.data(Qt.ItemDataRole.UserRole) if rid else None
            target = next((r for r in records if r.get("id") == cur_id), records[0])
        if not target:
            tooltip("AnkAI：请先选择一条历史")
            return
        self.panel.load_session(target)
        self.accept()

    def delete_selected(self) -> None:
        records = self._selected_records()
        if not records:
            tooltip("AnkAI：请先选择要删除的历史（可 Ctrl/Shift 多选）")
            return
        from aqt.qt import QMessageBox

        ret = QMessageBox.question(
            self, "AnkAI", f"确定删除所选 {len(records)} 条历史吗？（不可恢复）"
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        history.delete_many({r.get("id") for r in records})
        self.refresh()

    def export_selected(self) -> None:
        records = self._selected_records() or list(self.records)
        if not records:
            tooltip("AnkAI：没有可导出的历史")
            return
        from pathlib import Path

        from aqt.qt import QFileDialog

        default_path = Path(__file__).resolve().parent.parent / "user_files"
        default_path.mkdir(parents=True, exist_ok=True)
        default_path = default_path / f"ankai_history_{time.strftime('%Y%m%d_%H%M')}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出解释历史", str(default_path), "Markdown (*.md);;所有文件 (*)"
        )
        if not path:
            return
        parts = [f"# AnkAI 解释历史导出\n", f"- 导出时间：{time.strftime('%Y-%m-%d %H:%M')}",
                 f"- 条数：{len(records)}\n"]
        for r in records:
            fmt = {"mirra": "米拉", "sentence": "例句"}.get(r.get("fmt", ""), r.get("fmt", ""))
            parts.append(f"\n\n---\n\n## {r.get('time', '')} · [{fmt}] {r.get('text', '')}\n\n")
            parts.append(r.get("log_md", ""))
        try:
            Path(path).write_text("".join(parts), encoding="utf-8")
            tooltip(f"AnkAI：已导出 {len(records)} 条到 {path}")
        except Exception as exc:
            tooltip(f"AnkAI：导出失败 {exc}")

    def clear_all(self) -> None:
        from aqt.qt import QMessageBox

        ret = QMessageBox.question(self, "AnkAI", "确定清空全部解释历史吗？（不可恢复）")
        if ret != QMessageBox.StandardButton.Yes:
            return
        history.clear()
        self.refresh()


class ExplainPanel(QDockWidget):
    def __init__(self, addon):
        from aqt import mw

        QDockWidget.__init__(self, "AnkAI 解释", mw)
        self.setObjectName("AnkAIExplainDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self)

        self.addon = addon
        self.messages: list[dict] = []
        self.log_md = ""  # 历史轮次（含追问）的显示缓冲
        self.turn_md = ""  # 当前轮流式缓冲
        self._dirty = False
        self.busy = False
        self._cards_busy = False  # 会话制卡抽取中（与对话 busy 分开）
        self.session: dict | None = None  # 当前会话元信息（用于历史存取）
        # 状态栏状态
        self._t0 = 0.0
        self._attempt = 0
        self._received = 0
        self._failed = False
        self._last_heartbeat = 0.0  # 最近一次流事件（含推理心跳）的时刻
        self._sel = ""  # 内容区当前划选

        container = QWidget()
        self._setup_ui(container)
        self.setWidget(container)
        self._apply_theme()
        self._timer = QTimer(self)
        self._timer.setInterval(_REPAINT_MS)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        self.hide()  # 初始不占地方；首次解释或工具栏按钮时出现

    # ---------- UI ----------

    def _setup_ui(self, container: QWidget) -> None:
        lay = QVBoxLayout(container)
        lay.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Vertical)
        lay.addWidget(splitter, 1)

        self.view = _ContentBrowser(self)
        self.view.selectionChanged.connect(self._on_view_selection)
        splitter.addWidget(self.view)

        bottom = QWidget()
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 4, 0, 0)
        bottom_lay.setSpacing(4)

        self.status = QLabel("")
        self.status.setVisible(False)
        self.status.setWordWrap(True)
        bottom_lay.addWidget(self.status)

        row = QHBoxLayout()
        self.quote_btn = QPushButton("❝ 引用")
        self.quote_btn.setEnabled(False)
        self.quote_btn.setToolTip("把内容区当前划选以引用形式插入输入框（也可在内容区右键）")
        self.quote_btn.clicked.connect(self._quote_from_button)
        row.addWidget(self.quote_btn)
        self.input = _InputEdit(self)
        row.addWidget(self.input, 1)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_followup)
        row.addWidget(self.send_btn)
        bottom_lay.addLayout(row)

        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([540, 110])

        btns = QHBoxLayout()
        for text, slot in (
            ("🎴 生成卡片", self.generate_cards),
            ("🕘 历史", self.show_history),
            ("新对话", self.new_conversation),
            ("复制全文", self.copy_all),
            ("隐藏", self.hide),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        # 尺寸走配置（设置界面可调），并做下限保护
        ui_cfg = self.addon.get_config().get("ui", {})
        self.resize(
            max(320, int(ui_cfg.get("panel_width", 560))),
            max(400, int(ui_cfg.get("panel_height", 640))),
        )

    def _apply_theme(self) -> None:
        from aqt.theme import theme_manager

        if theme_manager.night_mode:
            self._muted = "#9a9a9e"
            self._error_fg = "#ff7b72"
            css = """
                QDockWidget, QTextBrowser, QPlainTextEdit { background-color: #1c1c1e; color: #e8e8e8; }
                h2 { color: #a3d977; font-size: 17px; border-bottom: 1px solid #3a3a3c;
                     padding-bottom: 3px; margin-top: 14px; }
                b { color: #ffd479; }
                code { background-color: #2c2c2e; color: #ff9eb3; }
                blockquote { color: #9a9a9e; border-left: 3px solid #3a3a3c; margin-left: 4px; }
                a { color: #6fbf73; }
            """
        else:
            self._muted = "#888"
            self._error_fg = "#c62828"
            css = """
                QDockWidget, QTextBrowser, QPlainTextEdit { background-color: #ffffff; color: #222; }
                h2 { color: #2e7d32; font-size: 17px; border-bottom: 1px solid #e0e0e0;
                     padding-bottom: 3px; margin-top: 14px; }
                b { color: #b26a00; }
                code { background-color: #f2f2f2; color: #c7254e; }
                blockquote { color: #666; border-left: 3px solid #e0e0e0; margin-left: 4px; }
                a { color: #2e7d32; }
            """
        self.setStyleSheet(css)
        self._dirty = True  # 主题切换后触发一次重渲染，让新配色立即生效

    def _wrap_html(self, body_html: str) -> str:
        return (
            "<html><body>"
            f"<div style='line-height:1.55'>{body_html}</div>"
            "</body></html>"
        )

    # ---------- 划选：朗读 / 解释 / 引用 ----------

    def _on_view_selection(self) -> None:
        self._sel = self.view.textCursor().selectedText().replace("\u2029", "\n").strip()
        self.quote_btn.setEnabled(bool(self._sel))

    def speak_selection(self, sel: str) -> None:
        text = " ".join(sel.split())
        if text:
            self.addon.speak(text)

    def quote_selection(self, sel: str) -> None:
        quoted = "\n".join("> " + line for line in sel.splitlines())
        cur = self.input.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.input.setTextCursor(cur)
        body = self.input.toPlainText()
        if body and not body.endswith("\n"):
            self.input.insertPlainText("\n")
        self.input.insertPlainText(quoted + "\n")
        self.input.setFocus()

    def _quote_from_button(self) -> None:
        if self._sel:
            self.quote_selection(self._sel)

    def quote_and_ask(self, sel: str, prefix: str) -> None:
        """把划选内容作为引用发送给 AI 继续解释（保持当前对话上下文）。"""
        if self.busy:
            tooltip("AnkAI：当前还在生成中")
            return
        if not self.messages:  # 还没有对话：当作全新解释
            fmt = self.addon.get_config()["explain"].get("default_format", "mirra")
            self.start_explain(sel, fmt)
            return
        quoted = "\n".join("> " + line for line in sel.splitlines())
        q = f"{prefix}：\n{quoted}"
        self.messages.append({"role": "user", "content": q + "\n" + FOLLOWUP_RULE})
        self.log_md += f"\n**🧑 {prefix}**\n\n{quoted}\n\n"
        self._failed = False
        self._start_turn()

    # ---------- 对话控制 ----------

    def start_explain(self, text: str, fmt: str) -> None:
        if self.busy or self._cards_busy:
            # 生成中重开解释会整体替换 self.messages，旧一轮完成时 _on_done
            # 会把旧回复追加进新会话并提前解除 busy，必须挡住
            tooltip(
                "AnkAI：正在提炼卡片候选，请等它完成再解释"
                if self._cards_busy
                else "AnkAI：当前还在生成中，稍后再解释"
            )
            return
        cfg = self.addon.get_config()
        self.messages = build_messages(
            text, fmt, custom_prompt=cfg["explain"].get("custom_prompt", "")
        )
        self.session = {
            "id": uuid.uuid4().hex[:12],
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "text": text[:200],
            "fmt": fmt,
        }
        self.log_md = ""
        fmt_label = {"mirra": "米拉解析", "sentence": "例句解析"}.get(fmt, fmt)
        snippet = text if len(text) <= 120 else text[:120] + "…"
        # 用 Markdown 写头部（面板渲染走 md_to_html，直接写 HTML 标签会被转义）
        self.log_md = f"**📌 {fmt_label}**\n\n{snippet}\n\n---\n\n"
        self._failed = False
        self._start_turn()

    def load_session(self, record: dict) -> None:
        """从历史回溯：恢复对话与显示，可继续追问。"""
        if self.busy or self._cards_busy:
            tooltip(
                "AnkAI：正在提炼卡片候选，请等它完成再切换历史"
                if self._cards_busy
                else "AnkAI：当前还在生成中，稍后再回溯"
            )
            return
        msgs = record.get("messages") or []
        if not msgs:
            tooltip("AnkAI：该历史记录为空")
            return
        self.messages = deepcopy(msgs)
        self.log_md = record.get("log_md", "")
        self.session = {
            "id": record.get("id") or f"{time.time():.0f}",
            "time": record.get("time", ""),
            "text": record.get("text", ""),
            "fmt": record.get("fmt", "mirra"),
        }
        self.turn_md = ""
        self._failed = False
        self.status.setVisible(False)
        self._dirty = True
        self.show()
        self.raise_()
        self.activateWindow()
        tooltip("AnkAI：已回到该历史对话，可继续追问")

    def show_history(self) -> None:
        # 单实例复用：反复开关不再累积隐藏的 QDialog；打开前刷新保证
        # 包含最新的解释轮次
        dlg = getattr(self, "_history_dlg", None)
        if dlg is None:
            dlg = HistoryDialog(self)
            self._history_dlg = dlg
        dlg.refresh()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def send_followup(self) -> None:
        q = self.input.toPlainText().strip()
        if not q or self.busy or not self.messages:
            return
        self.input.clear()
        # 发给模型的带精简约束，面板里只显示用户原话
        self.messages.append({"role": "user", "content": q + "\n" + FOLLOWUP_RULE})
        quoted_md = _quote_markdown(q)
        self.log_md += f"\n**🧑 追问**\n\n{quoted_md}\n\n"
        self._failed = False
        self._start_turn()

    def new_conversation(self) -> None:
        if self.busy or self._cards_busy:
            tooltip(
                "AnkAI：正在提炼卡片候选，请等它完成再开新对话"
                if self._cards_busy
                else "AnkAI：当前还在生成中"
            )
            return
        self.messages = []
        self.log_md = ""
        self.turn_md = ""
        self.session = None
        self._failed = False
        self.status.setVisible(False)
        self._dirty = True

    def copy_all(self) -> None:
        from aqt.qt import QApplication

        QApplication.clipboard().setText(self.log_md + self.turn_md)
        tooltip("AnkAI：已复制全文")

    # ---------- 会话制卡 ----------

    def generate_cards(self) -> None:
        """把当前会话内容提炼成 EnWords 卡片候选，由用户挑选后写入任意牌组。"""
        if self.busy or self._cards_busy:
            tooltip(
                "AnkAI：正在提炼卡片候选…（LLM 调用中，完成后会自动弹出制卡窗口）"
                if self._cards_busy
                else "AnkAI：当前还在生成中"
            )
            return
        if not self.messages:
            tooltip("AnkAI：还没有对话内容——先划选文字触发一次 AI 解释")
            return
        self._cards_busy = True
        self.status.setVisible(True)
        self.status.setStyleSheet(f"color: {self._muted};")
        self.status.setText("🎴 正在从会话中提炼卡片候选…")
        # 快照与“来源”都在点击时固定：提炼期间禁止切换会话，但即便将来放宽，
        # 也不能让完成时的 self.session 串进来源字段
        snapshot = list(self.messages)
        session = self.session or {}
        source = f"AnkAI {session.get('time', '')}".strip()
        self.addon.run_in_background(lambda: self._cards_work(snapshot, source))

    def _cards_work(self, snapshot: list[dict], source: str) -> None:
        from .cardgen import extract_candidates
        from .util import log, log_exc

        try:
            cfg = self.addon.get_config()
            candidates = extract_candidates(snapshot, cfg, source=source)
        except Exception as exc:
            log_exc("generate_cards")
            self.addon.run_on_main(lambda e=exc: self._cards_error(e))
            return
        log(f"cards extracted n={len(candidates)}")
        self.addon.run_on_main(lambda cs=candidates: self._on_candidates(cs))

    def _cards_error(self, exc: Exception) -> None:
        self._cards_busy = False
        self.status.setText(f"❌ {str(exc)[:200]}")
        self.status.setStyleSheet(f"color: {self._error_fg};")
        tooltip(f"AnkAI：制卡失败——{str(exc)[:100]}")

    def _on_candidates(self, candidates: list) -> None:
        from .cards_dialog import CardCandidatesDialog

        self._cards_busy = False
        self.status.setVisible(False)
        dlg = CardCandidatesDialog(self, candidates)
        dlg.exec()

    # ---------- 后台调用与流式 ----------

    def _start_turn(self) -> None:
        cfg = self.addon.get_config()
        snapshot = list(self.messages)
        self.busy = True
        self._failed = False
        self._t0 = time.monotonic()
        self._attempt = 0
        self._received = 0
        self._last_heartbeat = 0.0
        self.send_btn.setEnabled(False)
        self.turn_md = ""
        self.status.setVisible(True)
        self._dirty = True
        self.addon.run_in_background(lambda: self._work(snapshot, cfg))

    def _work(self, snapshot: list[dict], cfg: dict) -> None:
        from .util import log, log_exc

        log("llm work start")

        def on_delta(piece):
            if piece is None:
                self.addon.run_on_main(self._reset_turn)
            else:
                self.addon.run_on_main(lambda p=piece: self._append_turn(p))

        try:
            reply = llm.chat(snapshot, cfg, on_delta)
        except Exception as exc:
            log_exc("llm work")
            self.addon.run_on_main(lambda e=exc: self._on_error(e))
            return
        log(f"llm work done chars={len(reply)}")
        self.addon.run_on_main(lambda r=reply: self._on_done(r))

    def _reset_turn(self) -> None:
        # 流式重试前会收到 None 哨兵：新一轮尝试开始
        self._attempt += 1
        self._received = 0
        self.turn_md = ""
        self._dirty = True

    def _append_turn(self, piece: str) -> None:
        if piece == "":
            # 空心跳：流活着但还没有正文（推理模型的思考阶段）
            self._last_heartbeat = time.monotonic()
            return
        self._received += len(piece)
        self.turn_md += piece
        self._dirty = True

    def _on_done(self, reply: str) -> None:
        if reply and not self.turn_md:
            self.turn_md = reply
        if not self.turn_md:
            self.turn_md = "（无输出）"
        self.messages.append({"role": "assistant", "content": self.turn_md})
        self.log_md += self.turn_md + "\n\n"
        self.turn_md = ""
        self.busy = False
        self.send_btn.setEnabled(True)
        self.status.setVisible(False)
        self._dirty = True
        self._save_history()

    def _on_error(self, exc: Exception) -> None:
        msg = str(exc)
        hint = ""
        if "claude CLI" in msg:
            hint = "\n\n💡 本机 claude 命令通道异常（通常是 claude 命令不可用、登录失效或网络故障）。\n可在 ⚙ 设置里切换「OpenAI 兼容 API」并填 base_url / API Key / 模型名。"
        self.log_md += f"\n⚠️ **出错了**：{msg}{hint}\n\n"
        self.turn_md = ""
        self.busy = False
        self._failed = True
        self.send_btn.setEnabled(True)
        tooltip(f"AnkAI：生成失败——{msg[:80]}")
        self._dirty = True

    def _save_history(self) -> None:
        if not self.session or not self.messages:
            return
        history.upsert(
            {
                **self.session,
                "messages": deepcopy(self.messages),
                "log_md": self.log_md,
            }
        )

    # ---------- 渲染与状态栏 ----------

    def _flush(self) -> None:
        self._update_status()
        if not self._dirty:
            return
        self._dirty = False
        body = self.log_md + self.turn_md
        bar = self.view.verticalScrollBar()
        # 必须在 setHtml 前取值：setHtml 后滚动条已重置，拿不到"用户原来在哪"
        was_at_bottom = bar.value() >= bar.maximum() - 8
        old_pos = bar.value()
        html = md_to_html(body) if body.strip() else _EMPTY_HTML
        self.view.setHtml(self._wrap_html(html))
        # 生成中内容只在末尾追加：停在底部才跟随新内容；向上翻阅时保持原位置
        bar.setValue(bar.maximum() if was_at_bottom else min(old_pos, bar.maximum()))

    def _update_status(self) -> None:
        if not self.busy:
            if self._failed and self.status.text() != "❌ 生成失败，原因见上方内容区":
                self.status.setText("❌ 生成失败，原因见上方内容区")
                self.status.setStyleSheet(f"color: {self._error_fg};")
            return
        secs = int(time.monotonic() - self._t0)
        if self._received > 0:
            text = f"✍️ 生成中… 已输出 {self._received} 字 · {secs}s"
        elif self._attempt > 1:
            spin = _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]
            text = f"{spin} 连接失败，自动重试中（第 {self._attempt} 次尝试）· {secs}s"
        elif self._last_heartbeat and time.monotonic() - self._last_heartbeat < 5:
            text = f"🧠 模型推理中… {secs}s（思考完成后开始输出）"
        else:
            spin = _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]
            text = f"{spin} 正在思考… {secs}s（首次生成需等待模型响应）"
        if text != self.status.text():  # 100ms 一tick，文本没变就不碰控件
            self.status.setText(text)
            self.status.setStyleSheet(f"color: {self._muted};")

    # ---------- 窗口行为 ----------

    def closeEvent(self, event) -> None:  # 关闭=隐藏，保留对话记录
        event.ignore()
        self.hide()


def _quote_markdown(q: str) -> str:
    """把用户输入（可能多行）渲染成 blockquote，超出 6 行折叠。"""
    lines = q.splitlines() or [q]
    if len(lines) > 6:
        shown = lines[:6]
        shown.append(f"…（共 {len(lines)} 行）")
    else:
        shown = lines
    return "\n".join("> " + line for line in shown)
