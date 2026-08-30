"""集合读写：EnWords 笔记类型引导、牌组列表、查重、批量添加。

所有函数都需要传入 collection 且在主线程调用（Anki 的集合不是线程安全的）。
"""

from __future__ import annotations

from .cardgen import CardCandidate
from .entemplate import AFMT, CSS, FIELDS, MODEL_NAME, QFMT, TEMPLATE_NAME


def ensure_enwords_model(col, model_name: str = MODEL_NAME):
    """返回可用的 EnWords 笔记类型：缺失则按内置定义创建；存在但缺字段则补齐。

    补齐字段是为了兼容用户从旧版 apkg（8 字段时代）导入的 EnWords，或被手动
    删过字段的模板——保证写入 10 字段不会报错，也不动用户已有的笔记。
    """
    mm = col.models
    model = mm.by_name(model_name)
    if model is None:
        model = mm.new(model_name)
        for fname in FIELDS:
            mm.addField(model, mm.new_field(fname))
        tmpl = mm.new_template(TEMPLATE_NAME)
        tmpl["qfmt"] = QFMT
        tmpl["afmt"] = AFMT
        mm.add_template(model, tmpl)
        model["css"] = CSS
        model["sortf"] = 0  # 排序字段 = 单词
        mm.add(model)
        return model
    have = {f["name"] for f in model["flds"]}
    for fname in FIELDS:
        if fname not in have:
            mm.addField(model, mm.new_field(fname))
    return model


def list_deck_names(col) -> list[str]:
    """全部可存放新笔记的牌组名（排除筛选牌组），排序后返回。"""
    return sorted(d["name"] for d in col.decks.all() if not d.get("dyn"))


def existing_words(col, deck: str, words: list[str]) -> set[str]:
    """在指定牌组里已存在（按“单词”字段）的词条，统一小写比较。"""
    out: set[str] = set()
    for word in words:
        q = f'deck:"{deck}" 单词:"{word.replace(chr(34), "")}"'
        try:
            if list(col.find_notes(q)):
                out.add(word.lower())
        except Exception:
            continue  # 搜索语法异常时当作不重复，让 add 阶段兜底
    return out


def add_candidates(
    col,
    candidates: list[CardCandidate],
    deck_name: str,
    tags: list[str],
    audio_names: dict[str, str] | None = None,
) -> tuple[int, int]:
    """把候选写入集合，返回 (added, skipped)。

    牌组不存在会创建；添加前逐张按“单词”字段查重，重复的跳过。
    audio_names 按 词条小写 → 媒体文件名 映射，命中时把 [sound:] 追加进
    单词字段（EnWords 正面脚本会自动播放）。
    """
    model = ensure_enwords_model(col)
    deck_id = col.decks.id(deck_name)
    audio_names = audio_names or {}
    added = skipped = 0
    for cand in candidates:
        if list(col.find_notes(f'单词:"{cand.word.replace(chr(34), "")}"')):
            skipped += 1
            continue
        note = col.new_note(model)
        for fname, value in cand.to_note_fields().items():
            note[fname] = value
        sound = audio_names.get(cand.word.lower())
        if sound:
            note["单词"] = f"{cand.word} [sound:{sound}]"
        for tag in tags:
            if tag:
                note.add_tag(tag)
        col.add_note(note, deck_id)
        added += 1
    return added, skipped
