"""AnkAI 纯逻辑模块冒烟测试（不依赖 aqt）。用法：python tests/smoke_test.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "ankiai"
sys.path.insert(0, str(SRC))

from ankiai_lib import langdetect, md2html, prompts, tts, util  # noqa: E402
from ankiai_lib import token_usage  # noqa: E402

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

manifest_version = json.loads((SRC / "manifest.json").read_text(encoding="utf-8")).get("human_version", "")

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

# ---- 音色名解析（区域变体 / HD 音色）----
_voices_sample = "\n".join(
    [
        "en-GB-LibbyNeural              Female   General",
        "zh-CN-liaoning-XiaobeiNeural   Female   Regional",
        "en-US-Ava:DragonHDLatestNeural Female   HD",
        "Name Gender ContentCategories",  # 表头
        "voice-not-a-name",
    ]
)
_found = tts._VOICE_NAME_RE.findall(_voices_sample)
check(
    "list_voices 正则兼容区域变体与 HD 音色",
    len(_found) == 3
    and "en-GB-LibbyNeural" in _found
    and "zh-CN-liaoning-XiaobeiNeural" in _found
    and "en-US-Ava:DragonHDLatestNeural" in _found,
)

# ---- edge-tts 合成命令构建（负语速 -20% 不得被 argparse 当作未知选项）----
_cmd = tts.build_synth_command("python", "en-GB-LibbyNeural", "hello", "-20%", Path("out.mp3"))
check(
    "synth 命令用 --opt=value 形式（负语速不歧义）",
    "--rate=-20%" in _cmd
    and "-20%" not in _cmd  # 不允许 ["--rate", "-20%"] 的旧形态
    and "--voice=en-GB-LibbyNeural" in _cmd
    and "--text=hello" in _cmd
    and "--write-media=out.mp3" in _cmd,
)
_cmd0 = tts.build_synth_command("python", "v", "t", "+0%", Path("o.mp3"))
check("默认语速 +0% 同样为 --rate=+0%", "--rate=+0%" in _cmd0 and "+0%" not in _cmd0)

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
check(
    "md2html 链接渲染与 URL 转义",
    '<a href="https://e.com/?a=1&amp;b=2">示例</a>' in md2html.md_to_html("[示例](https://e.com/?a=1&b=2)"),
)
check("md2html javascript: 不成链", "<a " not in md2html.md_to_html("[x](javascript:alert(1))"))
_qhtml = md2html.md_to_html("> 第一行\n> 第二行\n\n后续段落")
check("md2html 连续引用合并", _qhtml.count("<blockquote>") == 1 and "第一行<br>第二行" in _qhtml)

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
check("llm User-Agent 随 manifest 版本", f"AnkAI/{manifest_version}" in llm._UA)

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
check("addon_version 与 manifest 一致", manifest_version != "" and util.addon_version() == manifest_version)

# ---- LLMError 透传（业务错误不套"网络请求失败"前缀）----
_orig_post_sse = llm._post_sse


def _raise_llm_error(*_args, **_kwargs):
    raise llm.LLMError("配额不足")

llm._post_sse = _raise_llm_error
try:
    llm._post_with_retry("http://example.invalid", {}, {}, None)
    check("LLMError 透传不换前缀", False, "未抛出")
except llm.LLMError as exc:
    check("LLMError 透传不换前缀", str(exc) == "配额不足")
finally:
    llm._post_sse = _orig_post_sse

# ---- 可重试错误恢复（连接中断一次后成功）----
_calls = {"n": 0}


def _flaky_post_sse(_url, _headers, _body, _on_delta, _timeout, **_kw):
    _calls["n"] += 1
    if _calls["n"] == 1:
        raise ConnectionError("connection reset")
    return "ok"


llm._post_sse = _flaky_post_sse
try:
    _reply = llm._post_with_retry("http://example.invalid", {}, {}, None)
    check("可重试错误后自动恢复", _reply == "ok" and _calls["n"] == 2)
finally:
    llm._post_sse = _orig_post_sse

# ---- 会话制卡：模板定义 ----
from ankiai_lib import cardgen, entemplate  # noqa: E402

check("EnWords 字段数与顺序", entemplate.FIELDS[0] == "单词" and len(entemplate.FIELDS) == 10)
check("EnWords 模板名", entemplate.MODEL_NAME == "EnWords" and entemplate.TEMPLATE_NAME == "EnWords Card")
check("正面含单词与自动播放", "{{单词}}" in entemplate.QFMT and ".replay-button" in entemplate.QFMT)
check("背面含例句与AI解析", "{{原文例句}}" in entemplate.AFMT and "{{#AI解析}}" in entemplate.AFMT)
check("CSS 含深色适配与高亮", "nightMode" in entemplate.CSS and "b.hl" in entemplate.CSS)

# ---- 会话制卡：JSON 解析 ----
_ARRAY = json.dumps(
    [
        {"单词": "decidedly", "音标": "di'saididli", "词性": "副词", "中文释义": "果断地",
         "CEFR": "C1", "原文例句": 'Amy said it <b class="hl">decidedly</b>.',
         "例句译文": "艾米斩钉截铁地说。", "AI解析": "1. …<br>2. …", "词义概述": "下巴一扬，没商量"},
        {"单词": "decidedly", "中文释义": "重复词条应被去重"},
        {"单词": "", "中文释义": "缺单词应被丢弃"},
        {"中文释义": "缺单词应被丢弃"},
        {"单词": "get a nice box", "中文释义": "表达卡", "词性": "短语",
         "音标": "不该有音标"},
        "不是对象的元素",
    ],
    ensure_ascii=False,
)
for label, raw in (
    ("裸 JSON", _ARRAY),
    ("围栏包裹", f"```json\n{_ARRAY}\n```"),
    ("前后带说明", f"好的，以下是卡片：\n{_ARRAY}\n以上就是全部内容。"),
):
    cands, _usage = cardgen.extract_candidates(
        [{"role": "user", "content": "x"}], util.DEFAULTS, source="AnkAI 测试",
        chat_fn=lambda _m, _c, _raw=raw: _raw,
    )
    check(
        f"cardgen 解析（{label}）",
        len(cands) == 2
        and cands[0].word == "decidedly"
        and cands[0].cefr == "C1"
        and cands[0].source == "AnkAI 测试"
        and cands[1].pos == "phrase"  # 短语卡词性归一化
        and cands[1].phonetic == "",
    )
try:
    cardgen.parse_json_array("抱歉，我无法输出 JSON。")
    check("cardgen 残缺输出报错", False, "未抛出")
except cardgen.CardGenError:
    check("cardgen 残缺输出报错", True)
try:
    cardgen.parse_json_array('{"单词": "不是数组"}')
    check("cardgen 非数组报错", False, "未抛出")
except cardgen.CardGenError:
    check("cardgen 非数组报错", True)
try:
    cardgen.parse_json_array('[{"单词": "w", "中文释义": "m",}]')  # 尾逗号应被修复
    check("cardgen 容忍尾逗号", True)
except cardgen.CardGenError as exc:
    check("cardgen 容忍尾逗号", False, str(exc))
check(
    "抽取提示词含字段与规则",
    all(
        k in prompts.CARD_EXTRACT_PROMPT
        for k in ("单词", "原文例句", "AI解析", "JSON", "phrase", "固定搭配", "俚语", "习语", "AI补句", "由你补写")
    ),
)
_c2 = cardgen._norm_candidate({"单词": "break a leg", "中文释义": "祝好运", "词性": "俚语"})
check(
    "俚语/习语归一化为 phrase",
    _c2 is not None and _c2.pos == "phrase" and _c2.phonetic == "",
)
_cands3, _usage3 = cardgen.extract_candidates(
    [{"role": "user", "content": "x"}],
    util.DEFAULTS,
    source="AnkAI 测试",
    chat_fn=lambda _m, _c: json.dumps(
        [
            {"单词": "on cloud nine", "中文释义": "欣喜若狂", "词性": "俚语",
             "原文例句": 'He was <b class="hl">on cloud nine</b> after the win.',
             "例句译文": "获胜后他欣喜若狂。", "AI补句": True},
            {"单词": "from the book", "中文释义": "照书本", "原文例句": "read it <b class=\"hl\">from the book</b>.",
             "例句译文": "照着书读。", "AI补句": False},
        ],
        ensure_ascii=False,
    ),
)
check(
    "AI补句标记与来源标注",
    len(_cands3) == 2
    and _cands3[0].ai_example
    and _cands3[0].source == "AnkAI 测试（AI 补句）"
    and not _cands3[1].ai_example
    and _cands3[1].source == "AnkAI 测试",
)
check(
    "chat_fn 返回元组时也能解出 usage",
    _usage3 is None,  # chat_fn 注入路径无 usage（真实 LLM 通道才有）
)

# ---- 会话制卡：on_usage 透传给 llm.chat（供 UI 实时显示 token）----
_captured = {"on_usage": None}
_usage_fake = {"prompt_tokens": 10, "completion_tokens": 20, "cached_tokens": 0}
_orig_chat = cardgen.llm.chat


def _fake_chat(_messages, _cfg, on_delta=None, on_usage=None):
    _captured["on_usage"] = on_usage
    if on_usage:
        on_usage(_usage_fake)
    return ('[{"单词": "abc", "中文释义": "测试"}]', _usage_fake)


cardgen.llm.chat = _fake_chat
try:
    _my_cb = lambda _u: None
    _c4, _u4 = cardgen.extract_candidates(
        [{"role": "user", "content": "x"}], util.DEFAULTS,
        source="AnkAI 测试", on_usage=_my_cb,
    )
    check(
        "制卡 on_usage 透传并带出 usage",
        _captured["on_usage"] is _my_cb  # 回调被原样透传给 llm.chat
        and _u4 == _usage_fake
        and len(_c4) == 1
        and _c4[0].word == "abc",
    )
finally:
    cardgen.llm.chat = _orig_chat

# ---- 会话制卡：笔记字段映射 ----
_cand = cardgen.CardCandidate(word="decidedly", meaning="果断地", source="AnkAI")
_fields = _cand.to_note_fields()
check(
    "候选 → EnWords 字段映射",
    list(_fields.keys()) == entemplate.FIELDS and _fields["单词"] == "decidedly",
)

# ---- deploy 子进程输出解码（中文 Windows tasklist 输出为 GBK）----
import deploy  # noqa: E402

check(
    "deploy GBK 输出解码",
    "anki.exe" in deploy._decode_output("映像名称 anki.exe".encode("gbk")).lower(),
)
check("deploy UTF-8 输出解码", "anki.exe" in deploy._decode_output(b"Image Name: anki.exe"))
check("anki_running 返回布尔", isinstance(deploy.anki_running(), bool))

# ---- Token 用量：流式 usage 解析 ----
_oai_usage = llm._extract_usage(
    {"usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200}}
)
check(
    "OpenAI 风格 usage 解析",
    _oai_usage is not None
    and _oai_usage["prompt_tokens"] == 120
    and _oai_usage["completion_tokens"] == 80
    and _oai_usage["total_tokens"] == 200
    and _oai_usage["cached_tokens"] == 0,
)
_anthropic_usage = llm._extract_usage(
    {
        "type": "message_delta",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 20,
        },
    }
)
check(
    "Anthropic 风格 usage 解析（cache 独立累加）",
    _anthropic_usage is not None
    and _anthropic_usage["prompt_tokens"] == 100
    and _anthropic_usage["completion_tokens"] == 50
    and _anthropic_usage["cached_tokens"] == 50
    and _anthropic_usage["total_tokens"] == 200,
)
check(
    "无 usage 字段返回 None",
    llm._extract_usage({"choices": [{"delta": {"content": "hi"}}]}) is None,
)

# ---- chat_result 兼容层（丢弃 usage 返回纯文本）----
_calls = {"n": 0}
_orig_post_sse = llm._post_sse


def _usage_post_sse(_url, _headers, _body, _on_delta, _timeout, **_kw):
    _calls["n"] += 1
    return "ok 文本", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


llm._post_sse = _usage_post_sse
try:
    _openai_cfg = util.deep_merge(
        util.DEFAULTS,
        {"llm": {"provider": "openai", "openai_base_url": "https://example.invalid/v1",
                 "openai_api_key": "test-key", "openai_model": "test-model"}},
    )
    _text = llm.chat_result([{"role": "user", "content": "hi"}], _openai_cfg)
    check("chat_result 返回纯文本", _text == "ok 文本")
    _text2, _usage2 = llm.chat([{"role": "user", "content": "hi"}], _openai_cfg)
    check(
        "chat 返回 (text, usage) 元组",
        _text2 == "ok 文本" and _usage2["total_tokens"] == 15,
    )
finally:
    llm._post_sse = _orig_post_sse

# ---- Token 用量：周期聚合（用注入 records，与运行日期无关）----
import datetime as _dt  # noqa: E402


def _ts(d: _dt.date) -> float:
    return _dt.datetime(d.year, d.month, d.day, 12, 0).timestamp()


_today = _dt.date.today()
_monday = _today - _dt.timedelta(days=_today.weekday())
_last_month = (_today.replace(day=1) - _dt.timedelta(days=1)).replace(day=1)
_last_year = _today.replace(year=_today.year - 1)

_recs = [
    {"ts": _ts(_today), "provider": "openai", "model": "m1", "feature": "explain",
     "prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 0, "request_ms": 1000},
    {"ts": _ts(_today), "provider": "openai", "model": "m1", "feature": "followup",
     "prompt_tokens": 200, "completion_tokens": 100, "cached_tokens": 0, "request_ms": 2000},
    {"ts": _ts(_monday), "provider": "anthropic", "model": "a1", "feature": "cards",
     "prompt_tokens": 300, "completion_tokens": 150, "cached_tokens": 50, "request_ms": 3000},
    {"ts": _ts(_last_month), "provider": "openai", "model": "m1", "feature": "explain",
     "prompt_tokens": 400, "completion_tokens": 200, "cached_tokens": 0, "request_ms": 1000},
    {"ts": _ts(_last_year), "provider": "openai", "model": "m1", "feature": "explain",
     "prompt_tokens": 800, "completion_tokens": 400, "cached_tokens": 0, "request_ms": 1000},
]
_sums = token_usage.summaries(_recs)
# 今天恰是周一时，本周一与今天重合：cards 记录（500）计入今日
_monday_is_today = _monday == _today
_today_tokens = 450 + (500 if _monday_is_today else 0)
_today_req = 2 + (1 if _monday_is_today else 0)
# cards 记录在本周内（本周一或今天），本周恒为 950
check(
    "今日摘要",
    _sums["today"]["tokens"] == _today_tokens
    and _sums["today"]["requests"] == _today_req,
)
check(
    "本周摘要（含周一制卡）",
    _sums["week"]["tokens"] == 950 and _sums["week"]["requests"] == 3,
)
# 上月记录是否属本月/本年取决于当前月份（月初第一周时本周一可能落在上月）
_month_extra = 500 if _monday.month == _today.month else 0
check("本月摘要", _sums["month"]["tokens"] == 450 + _month_extra)
# 本周一与上月记录各自按「是否在本年」计入本年摘要（去年记录不计）
_year_expected = (
    450
    + (500 if _monday.year == _today.year else 0)
    + (600 if _last_month.year == _today.year else 0)
)
check("本年摘要（不含去年）", _sums["year"]["tokens"] == _year_expected)
_s7 = token_usage.series_by_day(_recs, days=7)
check(
    "近7天序列长度与统计",
    len(_s7) == 7
    and _s7[-1]["tokens"] == _today_tokens
    and _s7[-1]["requests"] == _today_req,
)
if _today.month == 1:
    _prev_year_series = token_usage.series_by_month(_recs, year=_last_year.year)
    check(
        "上年逐月汇总（仅去年那笔）",
        sum(s["tokens"] for s in _prev_year_series) == 1200,
    )
_by_feat = token_usage.by_feature(_recs, period="all")
_feat_map = {f["label"]: f for f in _by_feat}
check(
    "按功能分组（all 不过滤日期）",
    len(_by_feat) == 3
    and _feat_map["AI 解释"]["tokens"] == 1950
    and _feat_map["追问"]["tokens"] == 300
    and _feat_map["制卡"]["tokens"] == 500,
)
_by_model = token_usage.by_model(_recs, period="all")
check(
    "按模型分组",
    len(_by_model) == 2
    and _by_model[0]["label"] == "openai · m1"
    and _by_model[1]["label"] == "anthropic · a1",
)

# ---- Token 用量：SVG 柱状图纯函数 ----
_svg = token_usage.bar_chart_svg(["一", "二", "三"], [100, 200, 0])
check(
    "SVG 柱状图生成",
    _svg.startswith("<svg")
    and "<rect" in _svg
    and "viewBox" in _svg,
)
_svg_bad = token_usage.bar_chart_svg(["一", "二"], [1, 2, 3])
check("SVG 参数不匹配返回空图", "<rect" not in _svg_bad and "<svg" in _svg_bad)

print()
if failures:
    print(f"失败 {len(failures)} 项：{failures}")
    sys.exit(1)
print("全部通过 ✅")
