"""Token 用量统计面板：摘要卡 + 柱状图 + 明细表。

数据全部来自 token_usage.py 的聚合函数（纯逻辑可测）；本模块只负责展示：
- 顶部四张摘要卡：今日 / 本周 / 本月 / 本年的 token 与请求数
- 中间柱状图：近 7 天 / 近 30 天 / 本年按月，QPainter 自绘（不依赖 HTML/SVG 渲染）
- 底部明细表：按功能（解释/追问/制卡）与按模型的用量分组
深浅主题适配沿用 panel.py 的 night_mode 判定。
"""

from __future__ import annotations

from aqt.qt import (
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    Qt,
    QVBoxLayout,
    QWidget,
)
from aqt.theme import theme_manager

from . import token_usage

_RANGE_LABELS = [("近 7 天", 7), ("近 30 天", 30), ("本年按月", 0)]
# 柱状图配色（深/浅主题）
_NIGHT_BG = "#1c1c1e"
_NIGHT_CARD = "#2c2c2e"
_NIGHT_TEXT = "#e8e8e8"
_NIGHT_MUTED = "#9a9a9e"
_NIGHT_BAR = "#6fbf73"
_NIGHT_GRID = "#3a3a3c"
_LIGHT_BG = "#ffffff"
_LIGHT_CARD = "#f4f4f4"
_LIGHT_TEXT = "#222222"
_LIGHT_MUTED = "#888888"
_LIGHT_BAR = "#2e7d32"
_LIGHT_GRID = "#e0e0e0"


def _fmt_compact(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}k"
    return str(v)


def _fmt_full(v: int) -> str:
    return f"{v:,}"


class _BarChart(QWidget):
    """纯 QPainter 柱状图：labels 与 values 等长。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels: list[str] = []
        self.values: list[int] = []
        self.setMinimumHeight(190)

    def set_data(self, labels: list[str], values: list[int]) -> None:
        self.labels = list(labels)
        self.values = [max(0, int(v)) for v in values]
        self.update()

    def paintEvent(self, _event) -> None:
        from aqt.qt import QColor, QPainter, QPen, QRectF

        night = theme_manager.night_mode
        text_c = QColor(_NIGHT_TEXT if night else _LIGHT_TEXT)
        muted_c = QColor(_NIGHT_MUTED if night else _LIGHT_MUTED)
        bar_c = QColor(_NIGHT_BAR if night else _LIGHT_BAR)
        grid_c = QColor(_NIGHT_GRID if night else _LIGHT_GRID)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(_NIGHT_BG if night else _LIGHT_BG))

        n = len(self.labels)
        if n == 0:
            painter.setPen(muted_c)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无用量数据")
            return

        pad_l, pad_r, pad_t, pad_b = 48, 12, 22, 30
        w, h = self.width(), self.height()
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        maxv = max(self.values) or 1

        # 网格线与 y 轴刻度
        painter.setPen(QPen(grid_c, 1))
        for i in range(5):
            y = pad_t + plot_h - plot_h * i / 4
            painter.drawLine(pad_l, int(y), pad_l + plot_w, int(y))
        painter.setPen(muted_c)
        for i in range(5):
            y = pad_t + plot_h - plot_h * i / 4
            painter.drawText(
                QRectF(0, y - 8, pad_l - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _fmt_compact(maxv * i // 4),
            )

        gap = 6 if n > 20 else (10 if n > 12 else (16 if n > 7 else 24))
        bar_w = (plot_w - gap * (n - 1)) / n
        if bar_w > 64:
            bar_w = 64
        step = (plot_w - bar_w) / n
        for i, (label, v) in enumerate(zip(self.labels, self.values)):
            x = pad_l + i * step + (step - bar_w) / 2
            bar_h = plot_h * v / maxv
            y = pad_t + plot_h - bar_h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bar_c)
            painter.drawRoundedRect(QRectF(x, y, bar_w, max(bar_h, 1)), 3, 3)
            if v > 0:
                painter.setPen(text_c)
                painter.drawText(
                    QRectF(x - 4, y - 16, bar_w + 8, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    _fmt_compact(v),
                )
            if n <= 14 or i % 2 == 0:
                painter.setPen(muted_c)
                painter.drawText(
                    QRectF(x - 14, h - pad_b, bar_w + 28, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )


class StatsDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("AnkAI Token 统计")
        self.resize(760, 620)
        self._build_ui()
        self._apply_theme()
        self.refresh_data()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 10)

        # 顶部四张摘要卡
        cards = QHBoxLayout()
        self.cards: dict[str, QLabel] = {}
        for key, label in (("today", "今日"), ("week", "本周"), ("month", "本月"), ("year", "本年")):
            frame = QFrame()
            frame.setObjectName("statCard")
            v = QVBoxLayout(frame)
            v.setContentsMargins(12, 10, 12, 10)
            title = QLabel(label)
            title.setObjectName("cardTitle")
            value = QLabel("—")
            value.setObjectName("cardValue")
            v.addWidget(title)
            v.addWidget(value)
            cards.addWidget(frame, 1)
            self.cards[key] = value
        lay.addLayout(cards)

        # 柱状图区
        group = QGroupBox("用量趋势")
        glay = QVBoxLayout(group)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(QLabel("范围"))
        self.range_combo = QComboBox()
        for label, _days in _RANGE_LABELS:
            self.range_combo.addItem(label)
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        top.addWidget(self.range_combo)
        glay.addLayout(top)
        self.chart = _BarChart()
        glay.addWidget(self.chart)
        lay.addWidget(group, 1)

        # 明细区
        self.tabs = QTabWidget()
        self.table_feature = self._make_table()
        self.table_model = self._make_table()
        self.tabs.addTab(self.table_feature, "按功能")
        self.tabs.addTab(self.table_model, "按模型")
        lay.addWidget(self.tabs, 1)

        # 底部
        bottom = QHBoxLayout()
        hint = QLabel("只统计能返回 usage 的 API 请求（claude-cli 与失败的请求不计）")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        bottom.addWidget(b_close)
        lay.addLayout(bottom)

    @staticmethod
    def _make_table() -> QTableWidget:
        t = QTableWidget(0, 3)
        t.setHorizontalHeaderLabels(["项目", "Token", "请求数"])
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    # ---------- 主题 ----------

    def _apply_theme(self) -> None:
        night = theme_manager.night_mode
        if night:
            self.setStyleSheet(
                "QDialog { background-color: %s; color: %s; }"
                "#statCard { background-color: %s; border: 1px solid %s; border-radius: 8px; }"
                "#cardTitle { color: %s; }"
                "#cardValue { color: %s; font-size: 19px; font-weight: bold; }"
                "#muted { color: %s; }"
                % (_NIGHT_BG, _NIGHT_TEXT, _NIGHT_CARD, _NIGHT_GRID, _NIGHT_MUTED, _NIGHT_TEXT, _NIGHT_MUTED)
            )
        else:
            self.setStyleSheet(
                "QDialog { background-color: %s; color: %s; }"
                "#statCard { background-color: %s; border: 1px solid %s; border-radius: 8px; }"
                "#cardTitle { color: %s; }"
                "#cardValue { color: %s; font-size: 19px; font-weight: bold; }"
                "#muted { color: %s; }"
                % (_LIGHT_BG, _LIGHT_TEXT, _LIGHT_CARD, _LIGHT_GRID, _LIGHT_MUTED, _LIGHT_TEXT, _LIGHT_MUTED)
            )

    # ---------- 数据 ----------

    def refresh_data(self) -> None:
        """重读用量文件并刷新全部视图（打开面板时调用）。"""
        records = token_usage.load()
        summaries = token_usage.summaries(records)
        for key, label in self.cards.items():
            s = summaries[key]
            label.setText(f"{_fmt_full(s['tokens'])} token · {s['requests']} 次")
        self._on_range_changed()
        self._fill_table(self.table_feature, token_usage.by_feature(records))
        self._fill_table(self.table_model, token_usage.by_model(records))

    def _on_range_changed(self) -> None:
        idx = self.range_combo.currentIndex()
        if idx < 0:
            idx = 0
        days = _RANGE_LABELS[idx][1]
        records = token_usage.load()
        if days > 0:
            series = token_usage.series_by_day(records, days=days)
        else:
            series = token_usage.series_by_month(records)
        self.chart.set_data([s["label"] for s in series], [s["tokens"] for s in series])

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[dict]) -> None:
        table.setRowCount(0)
        if not rows:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("暂无数据"))
            for c in range(1, 3):
                table.setItem(0, c, QTableWidgetItem(""))
            return
        for i, row in enumerate(rows):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(row["label"]))
            table.setItem(i, 1, QTableWidgetItem(_fmt_full(row["tokens"])))
            table.setItem(i, 2, QTableWidgetItem(str(row["requests"])))
        table.resizeColumnsToContents()
