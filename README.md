# 🖥️ WeChat-OpenCode

**用聊天操控电脑的 AI 管家** — 通过飞书向电脑发送指令，AI 自动执行。

```
手机发: "把桌面来宾市简介发给我"
  → 意图分析: ① AI找文件 ② /file发送
  → 自动拆解、顺序执行、结果发回手机
```

## 能力一览

| 类别 | 功能 |
|------|------|
| 🧠 意图识别 | 三层分析：/前缀命令 → LLM 分类，自动路由 |
| 🔀 任务拆解 | 复合任务自动拆解为步骤，逐步执行 |
| 💻 编程 | 写代码、修 bug、搭项目、跑测试 |
| 🖥️ 操控 | 截图、窗口管理、打开应用、文件传递 |
| ⏰ 定时 | 中文表达式创建定时任务（每天/每N分钟/工作日） |
| 📦 扩展 | MCP 协议，可装任意插件 |
| 🔄 自愈 | 任务失败自动重试 3 次 + Git 自动回滚 |
| 🛑 中断 | 新消息自动取消 Worker，/cancel 三重取消 |
| 📊 监控 | Web 管理面板 + 进度报告 + 费用追踪 |
| 📱 飞书 | 私聊 + 群聊 @机器人，图片/文件/语音 |

## 系统架构

```
你的手机 (飞书)
       │
       ▼
┌─────────────┐    ┌──────────────┐
│ 监工 :4097  │◄──►│ 执行层 :4098 │
│ 理解/派活    │    │ 干活/安装     │
│ 永不重启     │    │ 可独立重启    │
└─────────────┘    └──────────────┘
       │                  │
       ▼                  ▼
   你的电脑            MCP/Skill
                     (任意扩展)
```

**双进程架构：** 监工（Supervisor）负责聊天和理解需求，Worker 负责执行具体任务。Worker 崩溃不影响聊天，可独立重启。

## 快速开始

### 前提条件

- Windows 10/11
- Python 3.10+
- Node.js 18+（用于安装 opencode CLI）
- 飞书账号（用于创建机器人）
- VC++ Redistributable（如遇 DLL 加载失败，安装 [VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)）

### 1. 安装 opencode CLI

本项目依赖 [opencode CLI](https://github.com/opencode-ai/opencode) 作为 AI 执行引擎：

```bash
npm install -g @opencode-ai/cli
```

### 2. 克隆并安装项目

```bash
git clone https://github.com/yourname/wechat-opencode.git
cd wechat-opencode

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 3. 准备工作

**获取 DeepSeek API Key：**
1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 注册 → API Keys → 创建 → 复制 `sk-...`
3. 设置为环境变量：`$env:DEEPSEEK_API_KEY = "sk-..."`

**创建飞书机器人：**
1. 访问 [飞书开放平台](https://open.feishu.cn/app)
2. 创建企业自建应用 → 添加「机器人」能力
3. 复制 **App ID** 和 **App Secret**
4. 在「权限管理」中开通：
   - `im:message:send_as_bot`
   - `获取用户发给机器人的消息`
5. 发布版本 → 等待审核通过

### 4. 配置

```bash
# 复制配置文件模板
copy config.example.yaml config.yaml

# 编辑 config.yaml，填入以下内容：
# - feishu.app_id（飞书 App ID）
# - feishu.app_secret（飞书 App Secret）
```

配置文件说明：

```yaml
bot_type: "feishu"           # 目前仅支持飞书模式
opencode:
  project_dir: "C:\\Users\\你的用户名"  # 你的项目目录
  serve_port: 4097            # 监工端口
  worker_serve_port: 4098     # 执行层端口
  command_timeout: 600        # 命令超时时间（秒）
feishu:
  app_id: "cli_xxx"           # 飞书应用 App ID
  app_secret: "xxx"           # 飞书应用 App Secret
```

### 5. 启动

```bash
python -m wechat_opencode
```

首次运行会自动打开配置向导（`http://127.0.0.1:8099`），按提示填入：
- DeepSeek API Key
- 飞书 App ID + App Secret
- 选择模型

配置完成后服务自动启动，浏览器打开 `http://127.0.0.1:8080` 管理面板。

### 6. 开始使用

在飞书中找到你的机器人，直接发消息：

```
你好                    → 聊天
帮我写个爬虫             → AI 自动执行
/screen                → 截取桌面
/file 报告.docx         → 发送文件
/help                  → 查看所有指令
```

## 全部指令

| 指令 | 缩写 | 说明 |
|------|------|------|
| 直接打字 | — | 和 AI 对话，自动分析意图分发 |
| `/help` | `/h` | 查看帮助 |
| `/model` | `/m` | 切换模型（flash/pro） |
| `/screen` | `/sc` | 截取电脑桌面 |
| `/file <路径>` | `/f` | 搜索并发送文件 |
| `/focus <应用>` | — | 切换窗口到前台 |
| `/open <应用/文件>` | `/o` | 打开应用或文件 |
| `/desktop` | `/d` | 显示桌面 |
| `/min` `/max` | — | 最小化/最大化窗口 |
| `/apps` | `/ap` | 列出运行中的应用 |
| `/ppt <主题>` | — | 生成 PPT |
| `/plan <目标>` | — | 规划并执行任务 |
| `/tasks` | `/ta` | 查看任务列表 |
| `/task N` | — | 查看任务详情 |
| `/status` | `/st` | 查看当前状态 |
| `/progress N` | `/pr` | 设置进度报告间隔 |
| `/cancel` | — | 取消当前任务 |
| `/undo` | — | 撤销上次操作 |
| `/sessions` | `/se` | 查看执行会话 |
| `/cost` | `/co` | 查看费用统计 |
| `/compact` | — | 压缩监工对话上下文 |
| `/compact all` | — | 同时压缩监工和执行层上下文 |
| `/cron` | — | 定时任务管理 |
| `/new` | — | 开启新会话 |
| `/restart` | — | 重启服务 |
| `/cleartasks` | — | 清空任务记录 |

> 所有指令支持前缀缩写。如 `/m` → `/model`，`/sc` → `/screen`。歧义时自动列出候选。

## 🔄 上下文自动管理

系统会在以下情况自动压缩对话上下文，避免上下文超出限制：
- 用户停止操作 **1 小时后**，且会话消息数超过 **300 条**，自动压缩
- 手动指令：`/compact`（仅监工）、`/compact all`（监工+执行层）

## 📦 扩展能力

Worker 执行层支持 MCP 协议，可安装任意插件：

```
告诉机器人: "帮我装个处理 Excel 的 MCP"
  → 执行层自动安装 → 独立重启（监工不受影响）
```

已内置：Playwright（浏览器自动化）、Filesystem（文件系统操作）。

## 故障排查

```bash
# 检查配置是否正确
python -m wechat_opencode --check

# 强制进入配置向导
python -m wechat_opencode --setup

# 查看日志
Get-Content wechat_opencode.log -Tail 50
```

**常见问题：**
- 飞书连接失败 → 检查 App ID/Secret，确认应用已发布
- 指令无响应 → 检查 `DEEPSEEK_API_KEY` 环境变量
- Web 面板打不开 → 确认端口 8080 未被占用
- 找不到 opencode CLI → 执行 `npm install -g @opencode-ai/cli`

## 开发

```bash
pip install -r requirements.txt
pytest tests/          # 141 个测试
python -m wechat_opencode --dry-run  # 不启动服务，仅测试
```

## License

MIT
