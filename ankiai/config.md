# AnkAI 配置说明

可通过 **工具 → 插件 → AnkAI → 配置** 编辑 JSON，或直接右键菜单里的 **⚙ AnkAI 设置…**（推荐）。

## llm — AI 解释用的语言模型

| 键 | 说明 |
|---|---|
| `provider` | `claude-cli`（默认，零 key）/ `openai`（任意 OpenAI 兼容端点）/ `anthropic` |
| `claude_cmd` | claude 命令名或完整路径 |
| `claude_model` | 留空用 claude 默认模型 |
| `openai_base_url` | 如 `https://api.deepseek.com/v1`、`http://localhost:11434/v1`（Ollama） |
| `openai_api_key` / `openai_model` | 对应端点的 key 与模型名 |
| `anthropic_api_key` / `anthropic_model` | Anthropic 官方 API |
| `temperature` / `max_tokens` | 生成参数 |

API Key 也可用环境变量 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`ANTHROPIC_API_KEY` 提供（优先级低于配置文件）。

## tts — 朗读

| 键 | 说明 |
|---|---|
| `python_cmd` | 调用 edge-tts 用的 Python 路径，留空自动探测系统 Python |
| `rate` | 语速，如 `+0%`、`-10%`、`+20%`（设置里为下拉可选+可自定义） |
| `voice_en` | 英语语音，默认英音女声 `en-GB-LibbyNeural`；设置里下拉可换全部音色（美音/澳音等） |
| `voice_ja` | 日语语音，默认 `ja-JP-NanamiNeural` |
| `voice_zh` | 中文语音，默认 `zh-CN-XiaoxiaoNeural` |
| `voice_ko` | 韩语语音，默认 `ko-KR-SunHiNeural` |
| `voice_ru` | 俄语语音，默认 `ru-RU-SvetlanaNeural` |
| `fallback_voice` | 未识别语言时的兜底语音 |

音色均通过设置界面的下拉框选择（打开设置时自动拉取全部可用音色，共 300+ 个）；语音按文本哈希缓存在插件目录 `user_files/tts/`，重复朗读零等待。

## explain — 解释格式

| 键 | 说明 |
|---|---|
| `default_format` | `mirra`（米拉四段式：翻译/词汇/语法解析/其他知识点）或 `sentence`（例句解析：逐项解析/整句解读/文化点/记忆钩子） |
| `custom_prompt` | 自定义系统提示词；填写后整体覆盖内置两种格式 |

## ui — 界面与其他

| 键 | 说明 |
|---|---|
| `panel_width` / `panel_height` | 解释面板的初始尺寸（px，最小 320×400），设置界面可调 |
| `debug_log` | `true` 时把调试日志写入 `user_files/ankiai.log`（排查问题用；文件超 1MB 自动轮转为 `.old`） |
