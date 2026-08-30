"""解释历史：JSON 文件存储（user_files/history.json），可检索、可回溯。

每条记录：{id, time, text, fmt, messages, log_md}
- messages: 完整对话（用于回溯后继续追问，保持上下文）
- log_md:   面板渲染用的 Markdown 日志快照
"""

from __future__ import annotations

import json
import time
from pathlib import Path

MAX_SESSIONS = 100


def _path() -> Path:
    base = Path(__file__).resolve().parent.parent / "user_files"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.json"


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
        # 文件损坏：先把原文件改名备份再返回空。若直接当空处理，
        # 下一次 upsert 会覆盖掉它，历史就彻底找不回来了。
        backup = ""
        try:
            backup = f"history.corrupt.{time.strftime('%Y%m%d_%H%M%S')}.json"
            _path().replace(_path().with_name(backup))
        except Exception:
            pass
        _log_exc(f"history.load（已备份为 {backup or '失败'}）")
        return []


def _write(records: list[dict]) -> None:
    try:
        _path().write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    except Exception:
        _log_exc("history.write")


def upsert(record: dict) -> None:
    """按 id 插入或更新（新记录排最前），并裁剪到上限。"""
    rid = record.get("id")
    records = [r for r in load() if r.get("id") != rid]
    records.insert(0, record)
    _write(records[:MAX_SESSIONS])


def delete(record_id: str) -> None:
    _write([r for r in load() if r.get("id") != record_id])


def delete_many(record_ids: set) -> None:
    _write([r for r in load() if r.get("id") not in record_ids])


def clear() -> None:
    _write([])
