"""轻量 Markdown → QTextBrowser 可渲染的 HTML 子集。"""

from __future__ import annotations

import html
import re


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+?)`", r"<code>\1</code>", s)
    return s


def md_to_html(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    # (是否有序, 文本)；混合类型时先冲刷，避免渲染错乱
    list_buf: list[tuple[bool, str]] = []
    in_code = False
    code_buf: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(line) for line in para) + "</p>")
            para.clear()

    def flush_list() -> None:
        if not list_buf:
            return
        ordered = list_buf[0][0]
        tag = "ol" if ordered else "ul"
        items = "".join(f"<li>{_inline(text)}</li>" for _, text in list_buf)
        out.append(f"<{tag}>{items}</{tag}>")
        list_buf.clear()

    def push_list_item(ordered: bool, text: str) -> None:
        if list_buf and list_buf[-1][0] != ordered:
            flush_list()
        list_buf.append((ordered, text))

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append("<pre>" + html.escape("\n".join(code_buf)) + "</pre>")
                code_buf.clear()
                in_code = False
            else:
                flush_para()
                flush_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        if not stripped:
            flush_para()
            flush_list()
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            flush_list()
            level = min(len(m.group(1)), 6)  # 提示词用 ## 小节标题，映射到 h2
            out.append(f"<h{level}>" + _inline(m.group(2)) + f"</h{level}>")
            continue

        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            flush_para()
            flush_list()
            out.append("<hr>")
            continue

        m = re.match(r"^>\s?(.*)$", stripped)
        if m:
            flush_para()
            flush_list()
            out.append("<blockquote>" + _inline(m.group(1)) + "</blockquote>")
            continue

        m = re.match(r"^(\d+)[.、)．]\s+(.*)$", stripped)
        if m:
            flush_para()
            push_list_item(True, m.group(2))
            continue

        m = re.match(r"^[-*•]\s+(.*)$", stripped)
        if m:
            flush_para()
            push_list_item(False, m.group(1))
            continue

        flush_list()
        para.append(stripped)

    if in_code and code_buf:
        out.append("<pre>" + html.escape("\n".join(code_buf)) + "</pre>")
    flush_para()
    flush_list()
    return "\n".join(out)
