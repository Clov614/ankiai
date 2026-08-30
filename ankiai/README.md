# AnkAI —— Anki 划选 AI 解释 + Edge TTS 朗读

在 Anki 复习界面**划选卡片任意文字 → 右键**：

- 🤖 **AI 解释（米拉格式）**：翻译 / 词汇（带读音）/ 语法解析 / 其他值得注意的知识点
- 🧩 **AI 例句解析**：逐项解析 / 整句解读 / 文化点 / 记忆钩子
- 🔊 **朗读所选 / 朗读整卡**：免费 Edge TTS（微软语音，无需 key），按内容自动换声——英文默认**英音**（en-GB-LibbyNeural），日文/中文/韩文/俄文自动切对应语音；全部音色在设置里下拉选择（300+ 可选）
- 解释结果在独立面板展示，支持**多轮追问**（像米拉 App 的底部输入框）、复制、历史回溯、深色主题跟随

快捷键（划选后直接按，不用右键）：

- `Ctrl+Shift+A`：AI 解释（默认格式）
- `Ctrl+Shift+S`：朗读（有所选读所选，无所选读整卡）
- `Ctrl+Shift+P`：显示 / 隐藏解释面板（隐藏只是收起，对话保留，随时唤回）

面板“隐藏”后恢复方式：右键菜单「💬 解释面板」、`Ctrl+Shift+P`、或 工具 → AnkAI 解释面板。

## 安装

要求 Anki 25.09 及以上（Qt6）。

**方式一：AnkiWeb**（发布后可用）

工具 → 插件 → 获取插件，输入插件代码；或直接在 [AnkiWeb 插件页](https://ankiweb.net/shared/addons) 搜索下载。

**方式二：手动安装 .ankiaddon**

1. 从 [GitHub Releases](https://github.com/Clov614/ankiai/releases) 下载 `ankiai-x.y.z.ankiaddon`
2. 双击文件，或 Anki 里 工具 → 插件 → 从文件安装
3. 重启 Anki

## 使用

1. 复习卡片 → 划选文字 → 右键 → 选动作；未划选时可"朗读整卡"
2. AI 解释默认走本机 `claude` 命令（零配置）；想用 DeepSeek/Kimi 等，右键 → ⚙ 设置里切换"OpenAI 兼容 API"并填 key
3. API Key 只保存在本机插件配置里，不会随卡片或日志外发

## 依赖

- TTS：系统 Python + `edge-tts`（首次朗读时插件会询问并自动安装；也可手动 `pip install edge-tts`）
- AI：三选一 —— 本机 claude CLI（默认）/ OpenAI 兼容端点 / Anthropic API

## 开发

- 源码目录即插件目录（`__init__.py` 在根部，内部包 `ankiai_lib`）
- `python deploy.py` 同步到 addons21（保留 meta.json 与 user_files）
- `python tests/smoke_test.py` 跑纯逻辑冒烟测试
- 重新加载：重启 Anki，或 工具 → 插件 里禁用再启用 AnkAI
- 打发布包：`python package.py`，输出 `dist/ankiai-<版本>.ankiaddon`

## 结构

```
ankiai/
├── __init__.py          # Anki 入口
├── manifest.json / config.json / config.md / LICENSE
├── deploy.py            # 部署脚本（开发用）
├── package.py           # 打发布包脚本
└── ankiai_lib/
    ├── hooks.py         # 主控制器（右键菜单 hook、pycmd 路由、动作编排）
    ├── selection.py     # 划选跟踪 JS（mouseup/selectionchange → pycmd 回传）
    ├── menu.py          # 右键菜单构建、卡片文本提取
    ├── prompts.py       # 米拉四段式 / 例句解析提示词
    ├── llm.py           # claude-cli / OpenAI SSE / Anthropic SSE，多轮对话
    ├── tts.py           # edge-tts 子进程合成 + sha1 缓存 + 播放
    ├── panel.py         # 解释面板（流式渲染 + 追问输入）
    ├── settings.py      # 设置对话框
    ├── history.py       # 解释历史存取
    ├── md2html.py       # 轻量 Markdown → HTML
    ├── langdetect.py    # Unicode 字符集语言粗判
    └── util.py          # 配置读写
```

适配 Anki 25.09（Qt6/PyQt6）；使用的 hooks：`webview_will_show_context_menu`、`webview_did_receive_js_message`、`reviewer_did_show_question/answer`。

## 许可

AGPL-3.0，见 [LICENSE](LICENSE)。
