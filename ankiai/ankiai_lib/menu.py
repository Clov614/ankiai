"""右键菜单构建与卡片文本提取。"""

from __future__ import annotations

import html as html_mod
import re

from aqt.qt import qconnect

TTS_CARD_CHARS = 3000


def strip_html(raw: str) -> str:
    s = re.sub(r"\[sound:[^\]]*\]", "", raw)
    s = re.sub(r"<style.*?</style>", "", s, flags=re.S | re.I)
    s = re.sub(r"<script.*?</script>", "", s, flags=re.S | re.I)
    s = re.sub(r"<rt[^>]*>.*?</rt>", "", s, flags=re.S | re.I)  # ruby 注音去重
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def visible_card_text(addon) -> str:
    mw = addon.mw
    card = getattr(mw.reviewer, "card", None)
    if card is None:
        return ""
    try:
        raw = card.question() if addon.side == "question" else card.answer()
    except Exception:
        return ""
    return strip_html(raw)[:TTS_CARD_CHARS]


def add_actions(addon, webview, menu) -> None:
    mw = addon.mw
    reviewer = getattr(mw, "reviewer", None)
    if reviewer is None or webview is not reviewer.web:
        return

    sel = (addon.selection or "").strip()
    menu.addSeparator()

    act_panel = menu.addAction("💬 解释面板（显示 / 隐藏，Ctrl+Shift+P）")
    qconnect(act_panel.triggered, addon.show_panel_toggle)
    menu.addSeparator()

    explain_label = f"🤖 AI 解释：{sel[:24]}…" if sel else "🤖 AI 解释（先划选文字）"
    act_mirra = menu.addAction(explain_label)
    act_mirra.setEnabled(bool(sel))
    qconnect(act_mirra.triggered, lambda: addon.explain("mirra"))

    sentence_label = "🧩 AI 例句解析" if sel else "🧩 AI 例句解析（先划选文字）"
    act_sentence = menu.addAction(sentence_label)
    act_sentence.setEnabled(bool(sel))
    qconnect(act_sentence.triggered, lambda: addon.explain("sentence"))

    menu.addSeparator()
    if sel:
        act_speak_sel = menu.addAction("🔊 朗读所选")
        qconnect(act_speak_sel.triggered, lambda: addon.speak(sel))
    act_speak_card = menu.addAction("🔊 朗读整卡")
    qconnect(act_speak_card.triggered, lambda: addon.speak(""))

    menu.addSeparator()
    act_conf = menu.addAction("⚙ AnkAI 设置…")
    qconnect(act_conf.triggered, addon.open_settings)
