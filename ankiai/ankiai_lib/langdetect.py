"""按 Unicode 字符集粗判语言，用于 TTS 选声与解释提示词里的音标体系。"""

from __future__ import annotations


def _count_in_range(text: str, lo: int, hi: int) -> int:
    return sum(1 for ch in text if lo <= ord(ch) <= hi)


def detect_lang(text: str) -> str:
    if not text:
        return "en"

    # 排除 CJK 标点/符号区（。、「」【】等不参与判断）
    letters = [ch for ch in text if ch.isalpha()]
    n_letters = len(letters)

    n_kana = _count_in_range(text, 0x3040, 0x30FF)
    n_hangul = _count_in_range(text, 0xAC00, 0xD7AF)
    n_cjk = _count_in_range(text, 0x4E00, 0x9FFF) + _count_in_range(text, 0x3400, 0x4DBF)
    n_cyrillic = _count_in_range(text, 0x0400, 0x04FF)
    n_latin = sum(1 for ch in letters if ch.isascii())

    if n_hangul > 0:
        return "ko"
    if n_kana > 0:
        return "ja"
    if n_cyrillic > 0 and n_cyrillic * 3 > max(n_letters, 1):
        return "ru"
    # 无假名的纯汉字：日语选区几乎总带假名（送假名/注音），故默认判为中文
    if n_cjk > 0 and n_cjk * 2 >= max(n_letters, 1):
        return "zh"
    return "en"
