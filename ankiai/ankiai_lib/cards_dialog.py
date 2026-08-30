"""制卡对话框：会话候选卡片 → 复选挑选 → 选牌组 → 写入集合。

添加分两段（借 panel.addon 的 taskman 封装排线程）：
1. 后台线程逐张合成单词发音（edge-tts，按文本哈希缓存，失败不挡批次）；
2. 回主线程把 mp3 收进 collection.media 并写笔记（集合操作必须在主线程）。
"""

from __future__ import annotations

import re

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from . import notes, tts
from .cardgen import CardCandidate

_TAG_SPLIT = re.compile(r"[\s,，]+")


class CardCandidatesDialog(QDialog):
    def __init__(self, panel, candidates: list[CardCandidate]):
        super().__init__(panel)
        self.panel = panel
        self.addon = panel.addon
        self.candidates = candidates
        self.setWindowTitle("AnkAI 制卡")
        self.resize(780, 560)
        self._adding = False
        self._row = -1  # 详情区当前绑定的候选下标
        self._last_deck = ""
        self._last_tags: list[str] = []

        cfg = self.addon.get_config().get("cards", {})

        self.deck_box = QComboBox()
        self.deck_box.setEditable(True)
        deck_names = notes.list_deck_names(self.addon.mw.col)
        self._deck_set = set(deck_names)
        self.deck_box.addItems(deck_names)
        completer = QCompleter(sorted(self._deck_set))
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.deck_box.setCompleter(completer)
        default_deck = cfg.get("default_deck") or self.addon.mw.col.decks.current()["name"]
        self.deck_box.setCurrentText(
            default_deck if default_deck in self._deck_set or not self._deck_set else deck_names[0]
        )

        self.tags_edit = QLineEdit(str(cfg.get("default_tags") or "ankiai"))
        self.audio_chk = QCheckBox("附加单词发音（edge-tts，自动朗读）")
        self.audio_chk.setChecked(bool(cfg.get("attach_word_audio", True)))

        self._build_ui()

        self._deck_timer = QTimer(self)
        self._deck_timer.setSingleShot(True)
        self._deck_timer.setInterval(300)
        self._deck_timer.timeout.connect(self._refresh_duplicates)
        self.deck_box.editTextChanged.connect(self._on_deck_text_changed)
        self._apply_theme()
        self._refresh_duplicates()
        self._load_detail(0)

    # ---------- UI ----------

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        body = QHBoxLayout()
        lay.addLayout(body, 1)

        left = QVBoxLayout()
        self.listw = QListWidget()
        self.listw.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.listw.itemChanged.connect(self._on_item_changed)
        left.addWidget(self.listw, 1)
        check_row = QHBoxLayout()
        b_all = QPushButton("全选")
        b_all.clicked.connect(lambda: self._set_all_checked(True))
        b_none = QPushButton("全不选")
        b_none.clicked.connect(lambda: self._set_all_checked(False))
        check_row.addWidget(b_all)
        check_row.addWidget(b_none)
        check_row.addStretch(1)
        self.hint = QLabel("")
        self.hint.setStyleSheet("color: gray;")
        check_row.addWidget(self.hint, 1)
        left.addLayout(check_row)
        body.addLayout(left, 5)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(8, 0, 0, 0)
        self.word_label = QLabel("")
        self.word_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        form.addRow(self.word_label)
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color: gray;")
        form.addRow(self.meta_label)
        self.meaning_edit = QPlainTextEdit()
        self.meaning_edit.setFixedHeight(58)
        form.addRow("中文释义", self.meaning_edit)
        self.example_edit = QPlainTextEdit()
        self.example_edit.setFixedHeight(70)
        self.example_edit.setToolTip("可含 HTML（<b class=\"hl\">…</b> 为模板的目标词高亮标记）")
        form.addRow("原文例句", self.example_edit)
        self.example_cn_edit = QPlainTextEdit()
        self.example_cn_edit.setFixedHeight(50)
        form.addRow("例句译文", self.example_cn_edit)
        self.analysis_edit = QPlainTextEdit()
        self.analysis_edit.setFixedHeight(96)
        form.addRow("AI解析", self.analysis_edit)
        self.memo_edit = QLineEdit()
        form.addRow("词义概述", self.memo_edit)
        form.addRow(
            "提示", QLabel("单词/音标/词性/CEFR 只读；其余可直接修改后添加")
        )
        body.addWidget(form_widget, 6)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("牌组"))
        bottom.addWidget(self.deck_box, 2)
        bottom.addWidget(QLabel("标签"))
        bottom.addWidget(self.tags_edit, 1)
        bottom.addWidget(self.audio_chk)
        lay.addLayout(bottom)

        btns = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        btns.addWidget(self.status, 1)
        self.browser_btn = QPushButton("在浏览器中查看")
        self.browser_btn.setVisible(False)
        self.browser_btn.clicked.connect(self._open_browser)
        btns.addWidget(self.browser_btn)
        self.add_btn = QPushButton("🎴 添加到牌组")
        self.add_btn.clicked.connect(self._on_add)
        btns.addWidget(self.add_btn)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        btns.addWidget(b_close)
        lay.addLayout(btns)

        self.listw.currentRowChanged.connect(self._on_row_changed)
        self._rebuild_list()

    def _apply_theme(self) -> None:
        from aqt.theme import theme_manager

        if theme_manager.night_mode:
            self.setStyleSheet(
                "QDialog { background-color: #1c1c1e; color: #e8e8e8; }"
                "QPlainTextEdit, QLineEdit, QComboBox, QListWidget"
                " { background-color: #2c2c2e; color: #e8e8e8; }"
            )
        else:
            self.setStyleSheet("")

    # ---------- 列表 ----------

    def _rebuild_list(self) -> None:
        self.listw.blockSignals(True)
        self.listw.clear()
        for cand in self.candidates:
            item = QListWidgetItem(self._item_text(cand))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked if cand.is_duplicate else Qt.CheckState.Checked
            )
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        n_checked = sum(1 for c in self.candidates if not c.is_duplicate)
        self.hint.setText(f"共 {len(self.candidates)} 张 · 默认勾选 {n_checked} 张")
        if self.candidates:
            self.listw.setCurrentRow(0)
        else:
            self._load_detail(-1)
        self.add_btn.setEnabled(bool(self.candidates))

    @staticmethod
    def _item_text(cand: CardCandidate) -> str:
        prefix = "⚠ " if cand.is_duplicate else ""
        meta = " · ".join(x for x in (cand.phonetic, cand.pos, cand.cefr) if x)
        text = cand.word if not meta else f"{cand.word}  ({meta})"
        if cand.meaning:
            text += f"  {cand.meaning[:22]}"
        return prefix + text

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.listw.count()):
            self.listw.item(i).setCheckState(state)

    # ---------- 详情绑定 ----------

    def _on_row_changed(self, row: int) -> None:
        self._save_detail()
        self._load_detail(row)

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self.hint.setText(f"已勾选 {len(self._checked_candidates())} 张")

    def _checked_candidates(self) -> list[CardCandidate]:
        out = []
        for i, cand in enumerate(self.candidates):
            item = self.listw.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                out.append(cand)
        return out

    def _save_detail(self) -> None:
        if not (0 <= self._row < len(self.candidates)):
            return
        cand = self.candidates[self._row]
        cand.meaning = self.meaning_edit.toPlainText().strip()
        cand.example = self.example_edit.toPlainText().strip()
        cand.example_cn = self.example_cn_edit.toPlainText().strip()
        cand.analysis = self.analysis_edit.toPlainText().strip()
        cand.memo = self.memo_edit.text().strip()

    def _load_detail(self, row: int) -> None:
        self._row = row
        if not (0 <= row < len(self.candidates)):
            self.word_label.setText("（无候选）")
            self.meta_label.setText("")
            for w in (self.meaning_edit, self.example_edit, self.example_cn_edit, self.analysis_edit):
                w.setPlainText("")
                w.setEnabled(False)
            self.memo_edit.setText("")
            self.memo_edit.setEnabled(False)
            return
        cand = self.candidates[row]
        self.word_label.setText(("⚠ " if cand.is_duplicate else "") + cand.word)
        self.meta_label.setText(" · ".join(x or "—" for x in (cand.phonetic, cand.pos, cand.cefr)))
        for w, value in (
            (self.meaning_edit, cand.meaning),
            (self.example_edit, cand.example),
            (self.example_cn_edit, cand.example_cn),
            (self.analysis_edit, cand.analysis),
        ):
            w.setPlainText(value)
            w.setEnabled(True)
        self.memo_edit.setText(cand.memo)
        self.memo_edit.setEnabled(True)

    # ---------- 牌组与查重 ----------

    def _on_deck_text_changed(self, _text: str) -> None:
        if not self._adding:
            self._deck_timer.start()

    def _refresh_duplicates(self) -> None:
        deck = self.deck_box.currentText().strip()
        if deck not in self._deck_set:
            return  # 新牌组名或输入中：不加查重标记，添加阶段兜底
        existing = notes.existing_words(
            self.addon.mw.col, deck, [c.word for c in self.candidates]
        )
        changed = False
        for cand in self.candidates:
            dup = cand.word.lower() in existing
            if dup != cand.is_duplicate:
                changed = True
            cand.is_duplicate = dup
        if changed:
            self._rebuild_list()

    # ---------- 添加 ----------

    def _on_add(self) -> None:
        if self._adding:
            return
        self._save_detail()
        selected = self._checked_candidates()
        if not selected:
            tooltip("AnkAI：请先勾选要添加的卡片")
            return
        deck = self.deck_box.currentText().strip()
        if not deck:
            tooltip("AnkAI：请选择或输入牌组名")
            return
        tags = [t for t in _TAG_SPLIT.split(self.tags_edit.text().strip()) if t]
        self._adding = True
        self._set_add_ui(False)
        self.status.setText("正在合成单词发音…")
        attach_audio = self.audio_chk.isChecked()
        cfg = self.addon.get_config()

        def work():
            audio_paths: dict[str, object] = {}
            if attach_audio:
                for cand in selected:
                    try:
                        audio_paths[cand.word.lower()] = tts.synth(cand.word, cfg)
                    except tts.EdgeTTSMissing as exc:
                        self.addon.run_on_main(
                            lambda p=exc.python: self.addon._offer_install(p)
                        )
                    except Exception:
                        pass  # 单张失败不挡批次：该卡不附音频
            self.addon.run_on_main(
                lambda: self._do_add(selected, deck, tags, audio_paths)
            )

        self.addon.run_in_background(work)

    def _do_add(self, selected, deck, tags, audio_paths) -> None:
        from aqt import mw

        from .util import log_exc, write_config

        try:
            audio_names: dict[str, str] = {}
            for key, path in audio_paths.items():
                try:
                    audio_names[key] = mw.col.media.add_file(str(path))
                except Exception:
                    pass
            added, skipped = notes.add_candidates(mw.col, selected, deck, tags, audio_names)
        except Exception as exc:
            log_exc("add_candidates")
            self._adding = False
            self._set_add_ui(True)
            self.status.setText(f"❌ 添加失败：{exc}")
            return

        cfg = self.addon.get_config()
        cfg.setdefault("cards", {})["default_deck"] = deck
        write_config(cfg)

        self._last_deck = deck
        self._last_tags = tags
        no_audio = len(selected) - len(audio_names) if self.audio_chk.isChecked() else 0
        # 本批已尝试过的（含被跳过的重复项）都从列表移除，避免反复困惑
        added_words = {c.word for c in selected}
        self.candidates = [c for c in self.candidates if c.word not in added_words]
        self._adding = False
        self._rebuild_list()
        self._set_add_ui(True)
        parts = [f"✓ 已添加 {added} 张到「{deck}」"]
        if skipped:
            parts.append(f"{skipped} 张已存在跳过")
        if no_audio > 0:
            parts.append(f"{no_audio} 张未附音频")
        self.status.setText("，".join(parts))
        if added:
            self.browser_btn.setVisible(True)
        if not self.candidates:
            self.add_btn.setEnabled(False)

    def _set_add_ui(self, enabled: bool) -> None:
        self.add_btn.setEnabled(enabled and bool(self.candidates))
        self.deck_box.setEnabled(enabled)
        self.tags_edit.setEnabled(enabled)
        self.audio_chk.setEnabled(enabled)
        self.listw.setEnabled(enabled)

    def _open_browser(self) -> None:
        from aqt import mw
        from aqt.dialogs import dialogs

        search = f'deck:"{self._last_deck}"' if self._last_deck else ""
        if self._last_tags:
            search += f' tag:{self._last_tags[0]}'
        try:
            dialogs.open("Browser", mw, search=search.strip())
        except Exception:
            tooltip("AnkAI：打开浏览器失败，请手动打开")

    # ---------- 窗口行为 ----------

    def closeEvent(self, event) -> None:
        self._save_detail()
        super().closeEvent(event)
