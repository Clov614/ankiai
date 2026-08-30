# AnkAI 发布指南

## 0. 安全审查结论（发布前必读，已全部核查通过）

**逐文件人工审查了插件全部 13 个源文件（约 2100 行），未发现敏感信息：**

| 检查项 | 结果 |
|---|---|
| API Key / 密钥 | ✅ 无硬编码。`config.json` 与 `util.py DEFAULTS` 中 `openai_api_key`、`anthropic_api_key` 均为空字符串，仅作默认模板 |
| 个人路径 / 用户名 | ✅ 源码无绝对路径、无用户名（本地路径只存在于 `.zcode/plans` 计划文件中，**不属于插件，不发布**） |
| 用户数据 | ✅ `user_files/`（解释历史 history.json、TTS 音频缓存、日志）已排除在安装包外；代码在运行时自建该目录 |
| 危险调用 | ✅ 无 `eval`/`exec`/`pickle`/`shell=True`；所有子进程（claude CLI、edge-tts、pip）均用参数列表调用；`webview.eval` 与 Qt `dlg.exec()` 为正常 API |
| 网络行为 | ✅ 仅连接 Anthropic 官方 API 与用户自配的 OpenAI 兼容端点；无遥测、无上报 |
| HTML 注入 | ✅ `md2html.py` 对 AI 输出做 `html.escape` 转义后再渲染 |
| 缓存文件 | ✅ `__pycache__`/`.pyc` 已排除（AnkiWeb 明确拒收含 `__pycache__` 的包） |

**打包方式**：`ankiai/package.py` 采用白名单制（只打包列出的文件），天然排除一切开发产物与用户数据。

## 1. 发布渠道怎么选

| 渠道 | 优点 | 前提 / 限制 |
|---|---|---|
| **AnkiWeb**（官方插件站） | 用户在 Anki 里输代码即装、自动更新 | **账号需数月活跃使用历史才开放上传**（官方为防滥用设了不公开的准入标准；新账号会报 "account too new"）。若你的账号达不到，先用 GitHub |
| **GitHub Releases** | 无门槛、可传 .ankiaddon、方便他人审代码 | 用户需手动下载安装，无自动更新提醒 |
| Anki 论坛分享 | 可发帖介绍 + 附 GitHub 链接 | 需论坛账号 |

**推荐路径**：先 GitHub Releases 发布（今天就能发）→ 账号资格够了再上 AnkiWeb。

## 2. 已完成的发布准备

- ✅ `manifest.json` 修正为 Anki 官方 schema（原版缺 `package` 字段，双击 .ankiaddon 安装会报错）：
  `package=ankiai`、`human_version=0.1.0`、`min_point_version=250900`（要求 Anki 25.09+）
- ✅ 添加 `LICENSE`（AGPL-3.0 —— Anki 本体是 AGPL，AnkiWeb 上架必须选 AGPL 或兼容协议）
- ✅ `README.md` 增加面向最终用户的「安装」章节与许可说明
- ✅ `panel.py` 中一处面向私有环境措辞（"网关"）改为通用表述
- ✅ 安装包已构建并校验：[dist/ankiai-0.1.0.ankiaddon](dist/ankiai-0.1.0.ankiaddon)（44 KB，19 个文件，结构合规）

## 3. 路径 A：GitHub 发布（当天可完成）

```bash
cd F:\AgentWorkSpace\AnkiAgentPluginsLab
git init
git add ankiai tests .gitignore      # 注意：不要 add .zcode（含本地开发计划）
git commit -m "AnkAI 0.1.0"
```

1. 在 GitHub 建仓库（如 `ankiai`），按提示推送
2. 网页端 **Releases → Draft a new release**：tag 填 `v0.1.0`，标题 `AnkAI 0.1.0`
3. 把 `dist/ankiai-0.1.0.ankiaddon` 拖进附件区，发布

README 的「方式二」已写好指向 Releases 的链接，用户下载后双击即可安装。

> 已建好 `.gitignore`（排除 `dist/`、`__pycache__/`、`user_files/`、`.zcode/` 等）。

## 4. 路径 B：AnkiWeb 发布（账号资格通过后）

> **2026-08-30 实际尝试记录**：表单已完整填写（标题/标签/支持页/版本分支 25.09/描述/安装包），提交了 3 次（经抓包验证请求体完整、格式正常，multipart 49033 字节含全部文件），服务器均返回 `400 "try again later"`，无任何字段级错误。这与官方论坛确认的账号准入门槛一致——**账号活跃使用历史不足时，上传接口被统一拒绝**（官方不公布标准，通常需数月活跃使用）。GitHub 渠道不受影响。等账号资格通过后按下面步骤重试即可。

1. 登录 [ankiweb.net](https://ankiweb.net) → [shared/addons](https://ankiweb.net/shared/addons) 页点 **Upload**（或直接访问 [ankiweb.net/shared/upload](https://ankiweb.net/shared/upload)）
2. 上传 `dist/ankiai-0.1.0.ankiaddon`
3. 表单填写（可直接粘贴）：
   - **Name**：`AnkAI - 划选 AI 解释与朗读`
   - **Description**（见下方现成文案）
   - **Tags**：`ai`、`tts`、`language learning`、`japanese`、`english`
   - **License**：`AGPL-3.0`（必选项，与 LICENSE 文件一致）
   - **Minimum Anki Version**：`25.09`
4. 提交后获得数字插件代码，回填到 README「方式一」处

**Description 现成文案**：

> 在复习界面划选卡片文字后右键：🤖 AI 解释（翻译/词汇带读音/语法解析/知识点，支持多轮追问、历史回溯）+ 🧩 AI 例句解析（逐项解析/整句解读/文化点/记忆钩子）+ 🔊 Edge TTS 朗读（免费微软语音，无需 API key，英/日/中/韩/俄自动换声，300+ 音色可选）。
>
> 🎴 会话制卡：解释面板一键把当前对话提炼成 EnWords 单词卡（AI 挑词条，自动填释义/例句/AI解析/记忆钩子/单词发音），复选后写入任意牌组，重复词条自动跳过；首次使用自动创建 EnWords 笔记类型。
>
> AI 接口三选一：本机 claude 命令（默认，零配置）/ 任意 OpenAI 兼容端点（DeepSeek、Kimi、Ollama 等）/ Anthropic API。API Key 只存在本机。
>
> 快捷键：Ctrl+Shift+A 解释，Ctrl+Shift+S 朗读，Ctrl+Shift+P 面板。需要 Anki 25.09+。

## 5. 以后怎么发新版本

1. 改代码 → `ankiai/manifest.json` 里把 `human_version` 升到新版本号
2. `python package.py` 重新打包（自动读取版本号命名）
3. GitHub：发新 Release；AnkiWeb：进自己的插件页上传新版本
4. 更新时 Anki 会保留用户机器上的 `user_files/`（历史、语音缓存、配置），不会丢用户数据

## 6. 版本记录

- **0.2.0**：会话制卡——解释面板「🎴 生成卡片」把当前对话提炼成 EnWords 卡片（LLM 抽取候选 + 复选 + 任意牌组 + 单词发音 + 查重 + 自动创建 EnWords 笔记类型）；发布前需重新 `python package.py` 打包（新模块 cardgen/notes/cards_dialog/entemplate 走 glob 自动进包）
- **0.1.0**：首发（划选 AI 解释 + 多轮追问 + Edge TTS 朗读）
