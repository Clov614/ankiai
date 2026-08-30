"""AnkAI 纯逻辑模块冒烟测试（不依赖 aqt）。用法：python tests/smoke_test.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "ankiai"
sys.path.insert(0, str(SRC))

from ankiai_lib import langdetect, md2html, prompts, tts, util  # noqa: E402

failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"{mark} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---- config.json 与 DEFAULTS 一致（键结构）----
cfg_disk = json.loads((SRC / "config.json").read_text(encoding="utf-8"))
merged = util.deep_merge(util.DEFAULTS, cfg_disk)
check("config.json 可解析且与 DEFAULTS 合并", merged["llm"]["provider"] in ("claude-cli", "openai", "anthropic"))

# ---- 语言检测 ----
cases = {
    "見ていたみたいなの はあるかもしれない": "ja",
    "Amy's eyes were full of tears, and she declared she would never speak of her pears again.": "en",
    "日本的道路很窄，所以在红绿灯等地方等待": "zh",
    "안녕하세요 반갑습니다": "ko",
    "こんにちは world": "ja",
    "": "en",
}
for text, want in cases.items():
    got = langdetect.detect_lang(text)
    check(f"langdetect {text[:14]!r} -> {want}", got == want, f"got {got}")

# ---- voice 映射 ----
check("英音 voice（默认）", tts.voice_for("hello world", util.DEFAULTS) == "en-GB-LibbyNeural")
check("日语 voice", tts.voice_for("見ていた", util.DEFAULTS) == "ja-JP-NanamiNeural")
check("中文 voice", tts.voice_for("红绿灯", util.DEFAULTS) == "zh-CN-XiaoxiaoNeural")
check("俄语 voice", tts.voice_for("привет как дела", util.DEFAULTS) == "ru-RU-SvetlanaNeural")
check(
    "voice 兜底与 DEFAULTS 一致",
    tts.voice_for("hello", {"tts": {}}) == "en-GB-LibbyNeural",
)

# ---- md2html ----
md = (
    "## 翻译\n\n"
    "“日本的话，因为道路很窄。”\n\n"
    "## 词汇\n\n"
    "1. **日本** [にほん / nihon] - 日本\n"
    "2. **道** [みち / michi] - 道路\n\n"
    "普通段落，带 **加粗** 与 `code` 和 *斜体*。\n"
)
html_out = md2html.md_to_html(md)
check("md2html 标题", "<h2>翻译</h2>" in html_out)
check("md2html 有序列表", "<ol><li><b>日本</b>" in html_out.replace(" ", "") or "<li><b>日本</b>" in html_out)
check("md2html 粗体", "<b>加粗</b>" in html_out)
check("md2html 转义", md2html.md_to_html("a < b & c").find("&lt;") > -1)

# ---- prompts ----
msgs = prompts.build_messages("見ていたみたいなの", fmt="mirra")
check("prompts 米拉 system", "米拉" not in msgs[0]["content"] and "## 翻译" in msgs[0]["content"])
check("prompts 日语注音提示", "假名" in msgs[0]["content"])
msgs2 = prompts.build_messages("tears fell", fmt="sentence")
check("prompts 例句解析 system", "逐项解析" in msgs2[0]["content"])
check("prompts 英语 IPA 提示", "IPA" in msgs2[0]["content"])
msgs3 = prompts.build_messages("anything", custom_prompt="自定义提示词XYZ")
check("prompts 自定义覆盖", msgs3[0]["content"] == "自定义提示词XYZ")
check("prompts user 包裹", msgs[1]["content"].startswith("【待解析内容】"))

# ---- llm 序列化 ----
from ankiai_lib import llm  # noqa: E402

conv = llm._serialize_conversation(msgs + [{"role": "assistant", "content": "回答"}, {"role": "user", "content": "追问"}])
check("llm 会话序列化", "【任务说明】" in conv and "【助手】" in conv and "追问" in conv)

# ---- llm 流事件解析（错误必须抛出，不能被当心跳吞掉）----
try:
    llm._extract_delta({"error": {"message": "配额不足"}})
    check("OpenAI 风格流中 error 抛出", False, "未抛出")
except llm.LLMError as e:
    check("OpenAI 风格流中 error 抛出", "配额不足" in str(e))
try:
    llm._extract_delta({"type": "error", "error": {"message": "overloaded"}})
    check("Anthropic 风格流中 error 抛出", False, "未抛出")
except llm.LLMError as e:
    check("Anthropic 风格流中 error 抛出", "overloaded" in str(e))
check(
    "正常 delta 不受影响",
    llm._extract_delta({"choices": [{"delta": {"content": "你好"}}]}) == "你好"
    and llm._extract_delta({"type": "content_block_delta", "delta": {"text": "hi"}}) == "hi",
)

# ---- Anthropic 角色交替（失败轮之后追问不再 400）----
merged = llm._merge_consecutive(
    [
        {"role": "user", "content": "第一问"},
        {"role": "user", "content": "失败后再问"},
        {"role": "assistant", "content": "答"},
        {"role": "user", "content": "追问"},
    ]
)
check(
    "连续同角色消息合并",
    len(merged) == 3
    and merged[0]["role"] == "user"
    and "第一问" in merged[0]["content"]
    and "失败后再问" in merged[0]["content"]
    and merged[1]["role"] == "assistant",
)

# ---- 配置默认值完整性 ----
check("debug_log 默认关闭", util.DEFAULTS["ui"]["debug_log"] is False)
check("voice_ru 默认存在", util.DEFAULTS["tts"]["voice_ru"].startswith("ru-RU"))
merged_cfg = util.deep_merge(util.DEFAULTS, cfg_disk)
check("config.json 含新键或回退默认", merged_cfg["ui"]["panel_width"] == util.DEFAULTS["ui"]["panel_width"])

print()
if failures:
    print(f"失败 {len(failures)} 项：{failures}")
    sys.exit(1)
print("全部通过 ✅")
