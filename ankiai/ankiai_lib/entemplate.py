"""EnWords 笔记类型定义（移植自 LanguagePreviewAgentFlow/scripts/make_anki_template.py）。

纯常量、不依赖 aqt：字段名、正反面模板、CSS 与 resources/anki/anki_template.apkg
里的定义完全一致，用于用户集合缺失 EnWords 笔记类型时自动代建，保证
「会话 → 制卡」开箱即用。
"""

from __future__ import annotations

MODEL_NAME = "EnWords"
TEMPLATE_NAME = "EnWords Card"

# 10 个字段，顺序即卡片排序依据（首字段“单词”为排序字段）
FIELDS: list[str] = [
    "单词",
    "音标",
    "词性",
    "中文释义",
    "CEFR",
    "原文例句",
    "例句译文",
    "来源",
    "AI解析",
    "词义概述",
]

CSS = """
.card { font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
        text-align: left; line-height: 1.7; }
.word { font-size: 34px; font-weight: bold; }
.meta { color: #888; font-size: 16px; margin: 4px 0 14px; }
.cefr { color: #2a7de1; font-weight: bold; }
.mean { font-size: 22px; margin-bottom: 10px; }
.sent { border-left: 3px solid #2a7de1; padding-left: 10px; color: #333; }
.sent b.hl { color: #c7254e; font-weight: bold;
             background: #fdeaea; padding: 0 2px; border-radius: 3px; }
.sent b.hard { color: #1e8449; font-weight: bold;
               border-bottom: 1px dashed #1e8449; }
.sent-cn { color: #888; margin-top: 4px; padding-left: 10px; }
.ai { margin-top: 10px; font-size: 15px; color: #444;
      background: #f2f7fc; padding: 8px 10px; border-radius: 6px; }
.ai-title { color: #2a7de1; font-weight: bold; margin-bottom: 4px; }
.memo { margin-top: 8px; font-size: 16px; color: #8a6d3b; font-style: italic; }
.src { color: #aaa; font-size: 13px; margin-top: 12px; text-align: right; }

/* 深色主题适配:Anki 深色模式会给卡片容器添加 nightMode 类,
   #333 等浅色主题文字在深色背景上会看不清,此处逐项覆盖 */
.card.nightMode { background: #26262a; }
.nightMode .word { color: #f2f2f2; }
.nightMode .meta { color: #9c9c9c; }
.nightMode .cefr { color: #6fb1ff; }
.nightMode .mean { color: #f2f2f2; }
.nightMode .sent { color: #e6e6e6; }
.nightMode .sent b.hl { color: #ff9eb3; font-weight: bold;
                        background: #4a2230; padding: 0 2px; border-radius: 3px; }
.nightMode .sent b.hard { color: #7fd8a4; border-bottom: 1px dashed #7fd8a4; }
.nightMode .sent-cn { color: #b0b0b0; }
.nightMode .ai { color: #cfcfcf; background: #31313a; }
.nightMode .ai-title { color: #6fb1ff; }
.nightMode .memo { color: #d9b96a; }
.nightMode .src { color: #7a7a7a; }
.nightMode hr { border-top: 1px solid #4a4a4e; }
"""


def autoplay_script(direction: int) -> str:
    """自动播放脚本:Anki 桌面端把 [sound:] 渲染成 .replay-button(click() 等价手动点击,
    播放走 Anki 原生通道);移动端渲染成 <audio> 标签,兜底调 play()。
    direction=-1 播第一个(正面=单词音);=1 播最后一个(背面=例句音,例句无音时回退单词音)。
    播放失败静默吞掉,不影响卡片复习。"""
    return (
        '<script>\n'
        '(function () {\n'
        "  'use strict';\n"
        '  var DIR = %d;\n'
        '  function enAutoplay() {\n'
        '    try {\n'
        "      var btns = document.querySelectorAll('.replay-button');\n"
        "      var auds = document.querySelectorAll('audio');\n"
        '      if (btns.length) {\n'
        '        (DIR > 0 ? btns[btns.length - 1] : btns[0]).click();\n'
        '        return;\n'
        '      }\n'
        '      if (auds.length) {\n'
        '        var a = (DIR > 0 ? auds[auds.length - 1] : auds[0]);\n'
        '        var p = a.play();\n'
        "        if (p && p.catch) { p.catch(function () {}); }\n"
        '      }\n'
        '    } catch (e) {}\n'
        '  }\n'
        "  var act = function () { window.setTimeout(enAutoplay, 300); };\n"
        "  if (document.readyState === 'loading') {\n"
        "    document.addEventListener('DOMContentLoaded', act);\n"
        '  } else {\n'
        '    act();\n'
        '  }\n'
        '})();\n'
        '</script>'
    ) % direction


QFMT = (
    '<div class="word">{{单词}}</div>\n'
    '<div class="meta">{{音标}} · {{词性}} · '
    '<span class="cefr">{{CEFR}}</span></div>\n'
    + autoplay_script(-1)
)

AFMT = (
    '{{FrontSide}}\n'
    '<hr id="answer">\n'
    '<div class="mean">{{中文释义}}</div>\n'
    '<div class="sent">{{原文例句}}</div>\n'
    '<div class="sent-cn">{{例句译文}}</div>\n'
    '{{#AI解析}}<div class="ai"><div class="ai-title">🤖 例句解析</div>'
    '{{AI解析}}</div>{{/AI解析}}\n'
    '{{#词义概述}}<div class="memo">💡 {{词义概述}}</div>{{/词义概述}}\n'
    '<div class="src">{{来源}}</div>\n'
    + autoplay_script(1)
)
