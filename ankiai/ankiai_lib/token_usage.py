"""Token 用量记录与统计（纯逻辑，无 aqt 依赖，可独立测试）。

记录追加式存 user_files/token_usage.json，沿用 history.py 的原子写 +
坏文件备份恢复。每条记录：
    {ts, provider, model, feature, prompt_tokens, completion_tokens, cached_tokens, request_ms}
- ts:            完成时刻的本地时间戳（epoch 秒，浮点）
- feature:       explain（AI 解释）/ followup（追问）/ cards（会话制卡）
- prompt/completion/cached: 见 _extract_usage 的约定：cached 只在 provider
  把它单列时才有值（Anthropic cache_*），OpenAI 的 cached 已含在 prompt_tokens
  内，记 0 避免重复计数。统计口径 tokens = prompt + completion + cached。

聚合函数都接受 records 参数便于测试注入；不传则读文件。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_RECORDS = 20000  # 约覆盖一年以上重度使用，超限丢弃最旧记录


def _path() -> Path:
    base = Path(__file__).resolve().parent.parent / "user_files"
    base.mkdir(parents=True, exist_ok=True)
    return base / "token_usage.json"


def _log_exc(prefix: str) -> None:
    try:
        from .util import log_exc

        log_exc(prefix)
    except Exception:
        pass


def load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        # 文件损坏：先改名备份再返回空，避免下一次写入覆盖丢数据
        backup = ""
        try:
            backup = f"token_usage.corrupt.{time.strftime('%Y%m%d_%H%M%S')}.json"
            _path().replace(_path().with_name(backup))
        except Exception:
            pass
        _log_exc(f"token_usage.load（已备份为 {backup or '失败'}）")
        return []


def _write(records: list[dict]) -> None:
    try:
        tmp = _path().with_name("token_usage.json.tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_path())
    except Exception:
        _log_exc("token_usage.write")


def record_usage(
    provider: str = "",
    model: str = "",
    feature: str = "explain",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    request_ms: int = 0,
    ts: float | None = None,
) -> None:
    """追加一条用量记录（新记录在前），裁剪到上限。"""
    records = load()
    records.insert(
        0,
        {
            "ts": round(ts if ts is not None else time.time(), 3),
            "provider": str(provider or ""),
            "model": str(model or ""),
            "feature": str(feature or "explain"),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cached_tokens": int(cached_tokens or 0),
            "request_ms": int(request_ms or 0),
        },
    )
    _write(records[:MAX_RECORDS])


# ---------- 聚合 ----------

_PERIOD_KEYS = ("today", "week", "month", "year", "all")


def _rec_date(r: dict) -> date | None:
    try:
        return datetime.fromtimestamp(float(r.get("ts") or 0)).date()
    except Exception:
        return None


def _tokens(r: dict) -> int:
    return int(r.get("prompt_tokens") or 0) + int(r.get("completion_tokens") or 0) + int(
        r.get("cached_tokens") or 0
    )


def _in_period(rec_date: date, period: str, now: datetime) -> bool:
    today = now.date()
    if period == "today":
        return rec_date == today
    if period == "week":
        return rec_date >= today - timedelta(days=today.weekday())
    if period == "month":
        return (rec_date.year, rec_date.month) == (today.year, today.month)
    if period == "year":
        return rec_date.year == today.year
    return True


def summaries(records: list[dict] | None = None) -> dict[str, dict[str, int]]:
    """今日/本周/本月/本年的 {tokens, requests} 摘要。"""
    records = load() if records is None else records
    now = datetime.now()
    out = {}
    for key in ("today", "week", "month", "year"):
        tokens = requests = 0
        for r in records:
            rd = _rec_date(r)
            if rd is not None and _in_period(rd, key, now):
                tokens += _tokens(r)
                requests += 1
        out[key] = {"tokens": tokens, "requests": requests}
    return out


def series_by_day(records: list[dict] | None = None, days: int = 7) -> list[dict]:
    """近 N 天逐日汇总（含今天），[{label, tokens, requests}]。"""
    records = load() if records is None else records
    today = date.today()
    buckets = {today - timedelta(days=i): [0, 0] for i in range(days - 1, -1, -1)}
    for r in records:
        rd = _rec_date(r)
        if rd in buckets:
            buckets[rd][0] += _tokens(r)
            buckets[rd][1] += 1
    return [
        {"label": d.strftime("%m-%d"), "tokens": b[0], "requests": b[1]}
        for d, b in buckets.items()
    ]


def series_by_month(records: list[dict] | None = None, year: int | None = None) -> list[dict]:
    """某年的逐月汇总（默认当年），[{label, tokens, requests}]。"""
    records = load() if records is None else records
    year = year or date.today().year
    out = []
    for m in range(1, 13):
        tokens = requests = 0
        for r in records:
            rd = _rec_date(r)
            if rd is not None and rd.year == year and rd.month == m:
                tokens += _tokens(r)
                requests += 1
        out.append({"label": f"{m}月", "tokens": tokens, "requests": requests})
    return out


def _grouped(records: list[dict], period: str, key_fn, label_fn) -> list[dict]:
    records = load() if records is None else records
    now = datetime.now()
    agg: dict[str, dict] = {}
    for r in records:
        rd = _rec_date(r)
        if rd is None or not _in_period(rd, period, now):
            continue
        k = key_fn(r)
        a = agg.setdefault(k, {"label": label_fn(r), "tokens": 0, "requests": 0})
        a["tokens"] += _tokens(r)
        a["requests"] += 1
    return sorted(agg.values(), key=lambda a: a["tokens"], reverse=True)


# 功能名 → 统计面板展示用中文标签（分组 key 仍用原始英文值）
_FEATURE_LABELS = {
    "explain": "AI 解释",
    "followup": "追问",
    "cards": "制卡",
}


def _feature_label(feature: str) -> str:
    return _FEATURE_LABELS.get(feature, feature or "explain")


def by_feature(records: list[dict] | None = None, period: str = "all") -> list[dict]:
    """按功能分组：[{label, tokens, requests}]，按 tokens 降序。"""
    return _grouped(
        records,
        period,
        key_fn=lambda r: r.get("feature") or "explain",
        label_fn=lambda r: _feature_label(r.get("feature") or "explain"),
    )


def by_model(records: list[dict] | None = None, period: str = "all") -> list[dict]:
    """按 提供方+模型 分组：[{label, tokens, requests}]，按 tokens 降序。"""
    return _grouped(
        records,
        period,
        key_fn=lambda r: f"{r.get('provider', '')}|{r.get('model', '')}",
        label_fn=lambda r: _model_label(r),
    )


def _model_label(r: dict) -> str:
    provider = r.get("provider") or ""
    model = r.get("model") or ""
    if not model:
        return provider or "未知"
    return f"{provider} · {model}"


# ---------- 图表（纯函数，供统计面板渲染内联 SVG） ----------

_NIGHT_BAR = "#6fbf73"
_NIGHT_AXIS = "#3a3a3c"
_NIGHT_TEXT = "#9a9a9e"
_LIGHT_BAR = "#2e7d32"
_LIGHT_AXIS = "#e0e0e0"
_LIGHT_TEXT = "#666"


def _fmt_compact(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}k"
    return str(v)


def bar_chart_svg(labels: list[str], values: list[int], night: bool = False) -> str:
    """生成内联 SVG 柱状图（零依赖）。返回完整可嵌入 <img> 的 <svg> 字符串。

    统计面板里把它编码成 data:image/svg+xml 放进 QTextBrowser 的 <img>，
    深浅主题由 night 决定配色。纯函数，无 Qt 依赖，可独立测试。
    """
    if not labels or len(labels) != len(values):
        return "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    n = len(labels)
    if n <= 7:
        bar_w, gap = 52, 18
    elif n <= 12:
        bar_w, gap = 34, 14
    else:
        bar_w, gap = 14, 6
    pad_l, pad_r = 12, 12
    top, base_h = 16, 24  # 顶部数值标签留白 + 底部日期标签区
    plot_h = 150
    width = pad_l + pad_r + n * (bar_w + gap) - gap
    height = top + plot_h + base_h

    bar = _NIGHT_BAR if night else _LIGHT_BAR
    axis = _NIGHT_AXIS if night else _LIGHT_AXIS
    text = _NIGHT_TEXT if night else _LIGHT_TEXT
    maxv = max(values) or 1

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' "
        f"width='100%' height='{height}'>",
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='transparent'/>",
    ]
    # 横向网格线与 y 轴刻度
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        parts.append(f"<line x1='{pad_l - 4}' y1='{y:.1f}' x2='{width - pad_r + 4}' y2='{y:.1f}' stroke='{axis}' stroke-width='1'/>")
        parts.append(
            f"<text x='0' y='{y + 3:.1f}' font-size='10' fill='{text}'>{_fmt_compact(maxv * i // 4)}</text>"
        )
    # 柱子 + 数值 + 日期标签（>14 个时日期隔一个显示避免重叠）
    for i, (label, v) in enumerate(zip(labels, values)):
        x = pad_l + i * (bar_w + gap)
        h = plot_h * v / maxv
        y = top + plot_h - h
        parts.append(f"<rect x='{x}' y='{y:.1f}' width='{bar_w}' height='{max(h, 1):.1f}' rx='3' fill='{bar}'>"
                     f"<title>{label}：{v:,} tokens</title></rect>")
        if v > 0:
            parts.append(
                f"<text x='{x + bar_w / 2:.1f}' y='{y - 3:.1f}' font-size='9' fill='{text}' text-anchor='middle'>{_fmt_compact(v)}</text>"
            )
        if n <= 14 or i % 2 == 0:
            parts.append(
                f"<text x='{x + bar_w / 2:.1f}' y='{height - 7}' font-size='9' fill='{text}' text-anchor='middle'>{label}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)
