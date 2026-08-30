"""会话 → 卡片候选：把面板对话发给 LLM 抽取 EnWords 字段并健壮解析。

纯逻辑、不依赖 aqt，LLM 调用方负责线程安排（后台线程调用 extract_candidates）。
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass

from . import llm
from .prompts import CARD_EXTRACT_PROMPT, FOLLOWUP_RULE

# 抽取时放宽输出额度、压低随机性：JSON 稳定性与单轮产出量都比聊天更重要
EXTRACT_TEMPERATURE = 0.2
EXTRACT_MIN_MAX_TOKENS = 4096
MAX_CANDIDATES = 20

# 来源字段里标注 AI 补写的例句（沿用 LanguagePreviewAgentFlow 的惯例）
AI_EXAMPLE_MARK = "（AI 补句）"

# LLM 需要输出的 9 个字段（“来源”由代码按会话信息填充）
_LLM_FIELDS = ("单词", "音标", "词性", "中文释义", "CEFR", "原文例句", "例句译文", "AI解析", "词义概述")

_PHRASE_POS = {
    "phrase", "短语", "词组", "表达", "搭配", "固定搭配", "句型", "短语动词",
    "俚语", "习语", "成语", "口语", "idiom", "slang", "collocation", "expression",
}


class CardGenError(Exception):
    """抽取或解析失败，信息直接展示给用户。"""


@dataclass
class CardCandidate:
    word: str = ""
    phonetic: str = ""
    pos: str = ""
    meaning: str = ""
    cefr: str = ""
    example: str = ""
    example_cn: str = ""
    source: str = ""
    analysis: str = ""
    memo: str = ""
    ai_example: bool = False  # 例句是模型补写的（会话中没有原句）
    is_duplicate: bool = False

    def to_note_fields(self) -> dict[str, str]:
        """按 EnWords 字段名生成待写入笔记的字段字典（单词字段不含音频）。"""
        return {
            "单词": self.word,
            "音标": self.phonetic,
            "词性": self.pos,
            "中文释义": self.meaning,
            "CEFR": self.cefr,
            "原文例句": self.example,
            "例句译文": self.example_cn,
            "来源": self.source,
            "AI解析": self.analysis,
            "词义概述": self.memo,
        }


def _transcript(messages: list[dict]) -> str:
    """把面板会话转成纯文本记录；追问消息带上的回答约束对制卡是噪音，剥掉。"""
    parts = []
    for m in messages:
        role = "用户" if m["role"] == "user" else "助手"
        content = str(m.get("content", "")).replace(FOLLOWUP_RULE, "").strip()
        if content:
            parts.append(f"【{role}】\n{content}")
    return "\n\n".join(parts)


def parse_json_array(text: str) -> list:
    """从模型输出中解析 JSON 数组：剥代码围栏、截取 [ ... ]，容忍尾逗号。"""
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        raise CardGenError(f"模型输出里没有 JSON 数组：{raw[:200]}")
    body = raw[start : end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # 常见小毛病：末尾多一个逗号
        try:
            data = json.loads(re.sub(r",\s*([\]}])", r"\1", body))
        except json.JSONDecodeError as exc:
            raise CardGenError(f"JSON 解析失败（{exc}）：{raw[:200]}") from exc
    if not isinstance(data, list):
        raise CardGenError(f"模型输出不是 JSON 数组：{raw[:200]}")
    return data


def _truthy(value: object) -> bool:
    """模型的布尔字段可能是 true/"true"/"是" 等多种写法，统一识别。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "y", "是", "真", "补句")


def _norm_candidate(obj: object) -> CardCandidate | None:
    """单个 JSON 对象 → 候选；缺单词或释义的丢弃，表达卡统一词性为 phrase。"""
    if not isinstance(obj, dict):
        return None
    word = " ".join(str(obj.get("单词") or "").split())
    meaning = str(obj.get("中文释义") or "").strip()
    if not word or not meaning:
        return None
    pos = str(obj.get("词性") or "").strip()
    phonetic = str(obj.get("音标") or "").strip()
    if pos.lower() in _PHRASE_POS:
        pos, phonetic = "phrase", ""
    return CardCandidate(
        word=word,
        phonetic=phonetic,
        pos=pos,
        meaning=meaning,
        cefr=str(obj.get("CEFR") or "").strip(),
        example=str(obj.get("原文例句") or "").strip(),
        example_cn=str(obj.get("例句译文") or "").strip(),
        analysis=str(obj.get("AI解析") or "").strip(),
        memo=str(obj.get("词义概述") or "").strip(),
        ai_example=_truthy(obj.get("AI补句")),
    )


def extract_candidates(
    messages: list[dict],
    cfg: dict,
    source: str = "",
    chat_fn=None,
) -> list[CardCandidate]:
    """从会话中提炼卡片候选。chat_fn 仅测试注入用。"""
    if not messages:
        raise CardGenError("当前会话还没有内容")
    call_cfg = deepcopy(cfg)
    llm_cfg = call_cfg.setdefault("llm", {})
    llm_cfg["temperature"] = EXTRACT_TEMPERATURE
    llm_cfg["max_tokens"] = max(int(llm_cfg.get("max_tokens") or 0), EXTRACT_MIN_MAX_TOKENS)
    llm_msgs = [
        {"role": "system", "content": CARD_EXTRACT_PROMPT},
        {"role": "user", "content": f"【会话记录】\n{_transcript(messages)}\n【会话结束】"},
    ]
    raw = (chat_fn or llm.chat)(llm_msgs, call_cfg)
    data = parse_json_array(raw)

    out: list[CardCandidate] = []
    seen: set[str] = set()
    for obj in data:
        cand = _norm_candidate(obj)
        if cand is None:
            continue
        key = cand.word.lower()
        if key in seen:
            continue
        seen.add(key)
        cand.source = source
        if cand.ai_example:
            cand.source = f"{source}{AI_EXAMPLE_MARK}" if source else "AI 补句"
        out.append(cand)
        if len(out) >= MAX_CANDIDATES:
            break
    if not out:
        raise CardGenError("没有从会话中提炼出可制卡的词条")
    return out
