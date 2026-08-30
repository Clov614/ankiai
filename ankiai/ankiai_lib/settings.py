"""设置对话框：直接读写 Anki 的插件配置。

语音选择全部用下拉框（打开设置时后台拉取 edge-tts 完整音色列表填充，
失败则回退内置精选列表），用户只需选择、无需手输。
"""

from __future__ import annotations

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    qconnect,
)

from . import tts
from .util import DEFAULTS, deep_merge, get_config_safe, set_debug_logging, write_config

PROVIDER_LABELS = [
    ("claude-cli", "Claude CLI（零 key，本机 claude 命令）"),
    ("openai", "OpenAI 兼容 API"),
    ("anthropic", "Anthropic 官方 API"),
]
FORMAT_LABELS = [
    ("mirra", "米拉四段式（翻译/词汇/语法/知识点）"),
    ("sentence", "例句解析（逐项/整句/文化/钩子）"),
]
RATE_PRESETS = ["-20%", "-10%", "+0%", "+10%", "+15%", "+20%", "+30%"]

# 常见音色的友好标签；未收录的音色显示原始名
VOICE_LABELS = {
    "en-GB-LibbyNeural": "Libby · 英音女声",
    "en-GB-SoniaNeural": "Sonia · 英音女声",
    "en-GB-MaisieNeural": "Maisie · 英音女声（少女）",
    "en-GB-RyanNeural": "Ryan · 英音男声",
    "en-GB-ThomasNeural": "Thomas · 英音男声",
    "en-US-AriaNeural": "Aria · 美音女声",
    "en-US-JennyNeural": "Jenny · 美音女声",
    "en-US-MichelleNeural": "Michelle · 美音女声",
    "en-US-AndrewNeural": "Andrew · 美音男声（多情感）",
    "en-US-BrianNeural": "Brian · 美音男声",
    "en-US-ChristopherNeural": "Christopher · 美音男声",
    "en-US-GuyNeural": "Guy · 美音男声",
    "en-AU-NatashaNeural": "Natasha · 澳音女声",
    "en-AU-WilliamNeural": "William · 澳音男声",
    "ja-JP-NanamiNeural": "Nanami · 日语女声",
    "ja-JP-KeitaNeural": "Keita · 日语男声",
    "zh-CN-XiaoxiaoNeural": "晓晓 · 中文女声",
    "zh-CN-XiaoyiNeural": "晓伊 · 中文女声",
    "zh-CN-YunxiNeural": "云希 · 中文男声（年轻）",
    "zh-CN-YunjianNeural": "云健 · 中文男声（浑厚）",
    "zh-CN-YunyangNeural": "云扬 · 中文男声（新闻）",
    "zh-TW-HsiaoChenNeural": "曉臻 · 台灣女聲",
    "ko-KR-SunHiNeural": "SunHi · 韩语女声",
    "ko-KR-InJoonNeural": "InJoon · 韩语男声",
}
_LANG_SUFFIX = {
    "en-GB": "英音", "en-US": "美音", "en-AU": "澳音", "en-IN": "印度音",
    "ja-JP": "日语", "zh-CN": "中文", "zh-TW": "台湾", "ko-KR": "韩语",
    "fr-FR": "法语", "de-DE": "德语", "es-ES": "西语", "ru-RU": "俄语",
}


def _combo(options: list[tuple[str, str]], current: str) -> QComboBox:
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    idx = box.findData(current)
    if idx >= 0:
        box.setCurrentIndex(idx)
    return box


def _voice_display(name: str) -> str:
    if name in VOICE_LABELS:
        return VOICE_LABELS[name]
    locale = "-".join(name.split("-")[:2])
    lang = _LANG_SUFFIX.get(locale, locale)
    nick = name.split("-")[-1].replace("Neural", "") if name else name
    return f"{nick} · {lang}" if name else "（未设置）"


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AnkAI 设置")
        self.setMinimumWidth(560)
        self.cfg = get_config_safe()

        lay = QVBoxLayout(self)
        lay.addWidget(self._llm_group())
        lay.addWidget(self._tts_group())
        lay.addWidget(self._explain_group())
        lay.addWidget(self._cards_group())
        lay.addWidget(self._ui_group())

        footer = QHBoxLayout()
        hint = QLabel("API Key 仅保存在本机 Anki 插件配置中；也支持 OPENAI_API_KEY / ANTHROPIC_API_KEY 环境变量")
        hint.setStyleSheet("color: gray;")
        footer.addWidget(hint, 1)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        footer.addWidget(btns)
        lay.addLayout(footer)

        self._load()
        self._refresh_voices_async()

    # ---------- 构建控件 ----------

    def _llm_group(self) -> QGroupBox:
        g = QGroupBox("LLM 接口")
        form = QFormLayout(g)
        self.provider = _combo(PROVIDER_LABELS, self.cfg["llm"].get("provider", "claude-cli"))
        form.addRow("接口类型", self.provider)
        self.claude_cmd = QLineEdit()
        self.claude_model = QLineEdit()
        form.addRow("claude 命令", self.claude_cmd)
        form.addRow("claude 模型（留空默认）", self.claude_model)
        self.openai_base = QLineEdit()
        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_model = QLineEdit()
        form.addRow("兼容 base_url", self.openai_base)
        form.addRow("兼容 API Key", self.openai_key)
        form.addRow("兼容 模型名", self.openai_model)
        self.anthropic_key = QLineEdit()
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_model = QLineEdit()
        form.addRow("Anthropic Key", self.anthropic_key)
        form.addRow("Anthropic 模型", self.anthropic_model)
        return g

    def _tts_group(self) -> QGroupBox:
        g = QGroupBox("语音（Edge TTS，免费无需 key）")
        form = QFormLayout(g)
        self.tts_python = QLineEdit()
        self.tts_python.setPlaceholderText("留空自动探测系统 Python")
        form.addRow("Python 路径", self.tts_python)

        self.rate = QComboBox()
        self.rate.setEditable(True)
        for preset in RATE_PRESETS:
            self.rate.addItem(preset)
        form.addRow("语速", self.rate)

        self.voice_en = self._voice_combo()
        self.voice_ja = self._voice_combo()
        self.voice_zh = self._voice_combo()
        self.voice_ko = self._voice_combo()
        self.voice_ru = self._voice_combo()
        form.addRow("英语 voice", self.voice_en)
        form.addRow("日语 voice", self.voice_ja)
        form.addRow("中文 voice", self.voice_zh)
        form.addRow("韩语 voice", self.voice_ko)
        form.addRow("俄语 voice", self.voice_ru)

        self.voice_status = QLabel("")
        self.voice_status.setStyleSheet("color: gray;")
        form.addRow("", self.voice_status)

        reset = QPushButton("恢复默认声音")
        qconnect(reset.clicked, self._reset_voices)
        form.addRow("", reset)
        return g

    def _voice_combo(self) -> QComboBox:
        box = QComboBox()
        for name in self._curated_voices():
            box.addItem(_voice_display(name), name)
        box.setCurrentIndex(-1)
        return box

    @staticmethod
    def _curated_voices() -> list[str]:
        return list(VOICE_LABELS.keys())

    def _explain_group(self) -> QGroupBox:
        g = QGroupBox("解释格式")
        form = QFormLayout(g)
        self.fmt = _combo(FORMAT_LABELS, self.cfg["explain"].get("default_format", "mirra"))
        form.addRow("默认格式", self.fmt)
        self.custom_prompt = QPlainTextEdit()
        self.custom_prompt.setPlaceholderText("留空使用内置提示词；填写后整体覆盖两种内置格式")
        self.custom_prompt.setFixedHeight(96)
        form.addRow("自定义提示词", self.custom_prompt)
        return g

    def _cards_group(self) -> QGroupBox:
        g = QGroupBox("🎴 制卡（会话 → EnWords 卡片，模板缺失时自动创建）")
        form = QFormLayout(g)
        self.cards_model = QLineEdit()
        form.addRow("笔记类型名", self.cards_model)
        self.cards_deck = QLineEdit()
        self.cards_deck.setPlaceholderText("留空使用当前牌组（制卡后会记住上次选择）")
        form.addRow("默认牌组", self.cards_deck)
        self.cards_tags = QLineEdit()
        form.addRow("默认标签", self.cards_tags)
        self.cards_audio = QCheckBox("制卡时自动附加单词发音（edge-tts，无需 key）")
        form.addRow("", self.cards_audio)
        return g

    def _ui_group(self) -> QGroupBox:
        g = QGroupBox("界面与其他")
        form = QFormLayout(g)
        self.panel_width = QSpinBox()
        self.panel_width.setRange(320, 1600)
        self.panel_width.setSuffix(" px")
        form.addRow("面板宽度", self.panel_width)
        self.panel_height = QSpinBox()
        self.panel_height.setRange(400, 1600)
        self.panel_height.setSuffix(" px")
        form.addRow("面板高度", self.panel_height)
        self.debug_log = QCheckBox("写调试日志到 user_files\\ankiai.log（排查问题时打开）")
        form.addRow("", self.debug_log)
        return g

    # ---------- 读写 ----------

    def _load(self) -> None:
        llm = self.cfg["llm"]
        self.claude_cmd.setText(llm.get("claude_cmd", "claude"))
        self.claude_model.setText(llm.get("claude_model", ""))
        self.openai_base.setText(llm.get("openai_base_url", ""))
        self.openai_key.setText(llm.get("openai_api_key", ""))
        self.openai_model.setText(llm.get("openai_model", ""))
        self.anthropic_key.setText(llm.get("anthropic_api_key", ""))
        self.anthropic_model.setText(llm.get("anthropic_model", ""))

        tts_cfg = self.cfg["tts"]
        self.tts_python.setText(tts_cfg.get("python_cmd", ""))
        self.rate.setEditText(tts_cfg.get("rate", "+0%"))
        for combo, key in self._voice_combos():
            self._set_voice(combo, tts_cfg.get(key, ""))

        self.custom_prompt.setPlainText(self.cfg["explain"].get("custom_prompt", ""))

        cards = self.cfg["cards"]
        self.cards_model.setText(cards.get("model_name", "EnWords"))
        self.cards_deck.setText(cards.get("default_deck", ""))
        self.cards_tags.setText(cards.get("default_tags", "ankiai"))
        self.cards_audio.setChecked(bool(cards.get("attach_word_audio", True)))

        ui = self.cfg["ui"]
        self.panel_width.setValue(int(ui.get("panel_width", 560)))
        self.panel_height.setValue(int(ui.get("panel_height", 640)))
        self.debug_log.setChecked(bool(ui.get("debug_log", False)))

    def _voice_combos(self) -> list[tuple[QComboBox, str]]:
        return [
            (self.voice_en, "voice_en"),
            (self.voice_ja, "voice_ja"),
            (self.voice_zh, "voice_zh"),
            (self.voice_ko, "voice_ko"),
            (self.voice_ru, "voice_ru"),
        ]

    def _set_voice(self, combo: QComboBox, value: str) -> None:
        if not value:
            combo.setCurrentIndex(-1)
            return
        idx = combo.findData(value)
        if idx < 0:  # 列表外的存量配置：保留可见
            combo.addItem(_voice_display(value), value)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)

    # ---------- 音色列表异步拉取 ----------

    def _refresh_voices_async(self) -> None:
        from aqt import mw

        self.voice_status.setText("正在获取可用音色列表…")

        def work():
            try:
                return tts.list_voices(self.tts_python.text().strip())
            except Exception:
                return []

        mw.taskman.run_in_background(work, on_done=self._on_voices_loaded, uses_collection=False)

    def _on_voices_loaded(self, future) -> None:
        if not self.isVisible():
            return  # 对话框已关闭：不再触碰控件
        voices = future.result()
        if not voices:
            self.voice_status.setText("未能获取完整音色列表（edge-tts 未安装或网络问题），仅显示常用音色")
            return
        self.voice_status.setText(f"已加载 {len(voices)} 个可用音色")

        def sort_key(name: str) -> tuple[str, str]:
            return (name.split("-")[0], name)

        for combo, _ in self._voice_combos():
            current = combo.currentData()
            combo.clear()
            for name in sorted(voices, key=sort_key):
                combo.addItem(_voice_display(name), name)
            self._set_voice(combo, current)

    # ---------- 保存 / 重置 ----------

    def _reset_voices(self) -> None:
        self.rate.setEditText(DEFAULTS["tts"]["rate"])
        for combo, key in self._voice_combos():
            self._set_voice(combo, DEFAULTS["tts"][key])

    def _save(self) -> None:
        cfg = self.cfg

        llm = cfg["llm"]
        llm["provider"] = self.provider.currentData()
        llm["claude_cmd"] = self.claude_cmd.text().strip() or "claude"
        llm["claude_model"] = self.claude_model.text().strip()
        llm["openai_base_url"] = self.openai_base.text().strip()
        llm["openai_api_key"] = self.openai_key.text().strip()
        llm["openai_model"] = self.openai_model.text().strip()
        llm["anthropic_api_key"] = self.anthropic_key.text().strip()
        llm["anthropic_model"] = self.anthropic_model.text().strip()

        tts_cfg = cfg["tts"]
        tts_cfg["python_cmd"] = self.tts_python.text().strip()
        tts_cfg["rate"] = self.rate.currentText().strip() or "+0%"
        for combo, key in self._voice_combos():
            tts_cfg[key] = combo.currentData() or ""

        cfg["explain"]["default_format"] = self.fmt.currentData()
        cfg["explain"]["custom_prompt"] = self.custom_prompt.toPlainText()

        cards = cfg["cards"]
        cards["model_name"] = self.cards_model.text().strip() or "EnWords"
        cards["default_deck"] = self.cards_deck.text().strip()
        cards["default_tags"] = self.cards_tags.text().strip()
        cards["attach_word_audio"] = self.cards_audio.isChecked()

        cfg["ui"]["panel_width"] = self.panel_width.value()
        cfg["ui"]["panel_height"] = self.panel_height.value()
        cfg["ui"]["debug_log"] = self.debug_log.isChecked()
        set_debug_logging(cfg["ui"]["debug_log"])  # 立即生效，无需重启

        write_config(deep_merge({}, cfg))
        self.accept()
