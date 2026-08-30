"""LLM 调用：claude-cli 子进程 / OpenAI 兼容 SSE / Anthropic SSE。纯标准库，后台线程调用。

流式约定：on_delta(None) 表示「重置当前轮缓冲」（重试前调用）；on_delta(str) 为增量。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from .util import subprocess_no_window_kwargs as _no_window_kwargs

RETRY_TIMES = 3
# 每个 socket 操作的超时：太长会让失败“静默挂住”很久（面板会一直空转）
REQUEST_TIMEOUT = 60


class LLMError(Exception):
    pass


def _backoff(attempt: int) -> None:
    time.sleep(2**attempt)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (429, 500, 502, 503, 504)
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def _extract_delta(obj: dict) -> str:
    # 错误事件：Anthropic 是 {"type":"error", "error":{...}}，部分 OpenAI 兼容网关
    # 直接流式发 {"error":{...}}（无 type 字段）。统一在此拦截，避免错误被当成
    # 空心跳吞掉后“假成功”。
    err = obj.get("error")
    if err:
        raise LLMError(str(err.get("message") or err) if isinstance(err, dict) else str(err))
    choices = obj.get("choices")
    if choices:
        delta = choices[0].get("delta") or {}
        return delta.get("content") or ""
    kind = obj.get("type")
    if kind == "content_block_delta":
        return (obj.get("delta") or {}).get("text") or ""
    return ""


def _post_sse(url: str, headers: dict, body: dict, on_delta, timeout: int) -> str:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            # python-urllib 的默认 UA 会被部分网关（Cloudflare 1010）整站拦截
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnkAI/0.1",
            **headers,
        },
    )
    chunks: list[str] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            piece = _extract_delta(obj)
            if piece:
                chunks.append(piece)
                if on_delta:
                    on_delta(piece)
            elif on_delta:
                # 无正文的事件（如 glm 等推理模型的 reasoning_content）也回报为
                # 空心跳，让 UI 知道流仍然活着，而不是一直停在“思考中”
                on_delta("")
    return "".join(chunks)


def _post_with_retry(url: str, headers: dict, body: dict, on_delta) -> str:
    last: Exception | None = None
    for attempt in range(RETRY_TIMES):
        if on_delta:
            on_delta(None)  # 通知 UI 重置当前轮缓冲
        try:
            return _post_sse(url, headers, body, on_delta, REQUEST_TIMEOUT)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                detail = str(exc)
            if _is_retryable(exc) and attempt < RETRY_TIMES - 1:
                last = exc
                _backoff(attempt)
                continue
            raise LLMError(f"HTTP {exc.code}：{detail}") from exc
        except Exception as exc:
            if _is_retryable(exc) and attempt < RETRY_TIMES - 1:
                last = exc
                _backoff(attempt)
                continue
            raise LLMError(f"网络请求失败：{exc}") from exc
    raise LLMError(f"重试 {RETRY_TIMES} 次后仍失败：{last}")


def chat_openai(messages: list[dict], cfg: dict, on_delta=None) -> str:
    c = cfg["llm"]
    base = (c.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")).rstrip("/")
    key = c.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
    model = c.get("openai_model") or os.environ.get("OPENAI_MODEL", "")
    if not base:
        raise LLMError("未配置 OpenAI 兼容 base_url（AnkAI 设置里填写，或设 OPENAI_BASE_URL 环境变量）")
    if not key:
        raise LLMError("未配置 API Key（AnkAI 设置里填写，或设 OPENAI_API_KEY 环境变量）")
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": c.get("temperature", 0.7),
        # 与 DEFAULTS 的 max_tokens 保持一致
        "max_tokens": c.get("max_tokens", 3072),
    }
    # OpenAI o 系列推理模型只认 max_completion_tokens 且不接受自定义 temperature
    if re.match(r"^o[1345](-|$)", model):
        body.pop("temperature", None)
        body["max_completion_tokens"] = body.pop("max_tokens")
    return _post_with_retry(
        base + "/chat/completions", {"Authorization": f"Bearer {key}"}, body, on_delta
    )


def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """合并连续同角色消息（Anthropic 要求 user/assistant 严格交替）。

    典型场景：一轮生成失败后没有 assistant 回复，用户接着追问，messages 里
    就会出现连续两条 user；不合并会被 API 以 400 拒绝。
    """
    merged: list[dict] = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": role, "content": content})
    return merged


def chat_anthropic(messages: list[dict], cfg: dict, on_delta=None) -> str:
    c = cfg["llm"]
    key = c.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise LLMError("未配置 Anthropic API Key（AnkAI 设置里填写，或设 ANTHROPIC_API_KEY 环境变量）")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = _merge_consecutive(
        [m for m in messages if m["role"] in ("user", "assistant")]
    )
    body: dict = {
        "model": c.get("anthropic_model") or "claude-sonnet-4-5",
        "messages": convo,
        "max_tokens": c.get("max_tokens", 3072),
        "stream": True,
    }
    if system:
        body["system"] = system
    if c.get("temperature") is not None:
        body["temperature"] = c["temperature"]
    return _post_with_retry(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
        body,
        on_delta,
    )


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _serialize_conversation(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        role = {"system": "任务说明", "user": "用户", "assistant": "助手"}.get(m["role"], m["role"])
        parts.append(f"【{role}】\n{m['content']}")
    parts.append("【助手】\n（请接着上面的记录直接给出回答，不要复述记录本身。）")
    return "\n\n".join(parts)


def chat_claude_cli(messages: list[dict], cfg: dict, on_delta=None) -> str:
    import shutil

    c = cfg["llm"]
    cmd = c.get("claude_cmd") or "claude"
    # Windows 下 claude 通常是 .cmd 脚本，CreateProcess 找不到裸命令名，需先解析
    resolved = shutil.which(cmd)
    if not resolved:
        raise LLMError(
            f"找不到命令 {cmd!r}（PATH 里没有）。请在 AnkAI 设置里填写 claude 的完整路径"
        )
    args = [resolved, "-p"]
    if c.get("claude_model"):
        args += ["--model", c["claude_model"]]
    prompt = _serialize_conversation(messages)
    try:
        proc = subprocess.run(
            args,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=c.get("claude_timeout", 300),
            **_no_window_kwargs(),
        )
    except FileNotFoundError:
        raise LLMError(f"无法启动 {resolved!r}，请在 AnkAI 设置里检查 claude 路径") from None
    except subprocess.TimeoutExpired:
        raise LLMError("claude CLI 响应超时") from None
    out = _decode(proc.stdout).strip()
    err = _decode(proc.stderr).strip()
    if proc.returncode != 0:
        raise LLMError(f"claude CLI 失败（code {proc.returncode}）：{(err or out)[:500]}")
    if not out:
        raise LLMError(f"claude CLI 无输出：{err[:500]}")
    if on_delta:
        on_delta(out)
    return out


def chat(messages: list[dict], cfg: dict, on_delta=None) -> str:
    provider = (cfg.get("llm", {}).get("provider") or "claude-cli").lower()
    if provider == "openai":
        return chat_openai(messages, cfg, on_delta)
    if provider == "anthropic":
        return chat_anthropic(messages, cfg, on_delta)
    return chat_claude_cli(messages, cfg, on_delta)
