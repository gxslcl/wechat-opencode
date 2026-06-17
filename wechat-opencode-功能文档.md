# WeChat-OpenCode 功能文档与操作手册

> 版本: 2026-06-16 | 消息总线 | 三层意图分析 | 上下文自动管理 | 定时任务

---

## 一、项目概述

**WeChat-OpenCode** 是一个将飞书消息桥接到 OpenCode AI 的智能机器人。用户通过飞书向机器人发送指令，机器人理解需求并自动执行——操作电脑、编写代码、管理文件、生成 PPT 等。

**核心理念**: 用聊天的方式操控电脑。

### 核心创新：消息总线

所有消息（飞书消息、Web 面板消息、系统回复）统一经过 **MessageBus**（消息总线），确保飞书端和 Web 面板实时同步。

```
用户飞书 → 总线 → 核心处理 → 总线 → 飞书回复
Web面板  → 总线 → 核心处理 → 总线 → Web 面板显示
```

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     用户 (飞书)                                │
│  私聊 / 群聊 @机器人                                           │
└──────────────────────────┬───────────────────────────────────┘
                           │ WebSocket 长连接 (lark-oapi)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     FeishuBot                                 │
│  · 接收文字/图片/文件   · 自动重连/去重/限流                   │
│  · 群聊 @机器人 触发     · 异步消息队列 (快速 ACK)             │
│  · 图片异步下载          · 速率限制自动降级                    │
└──────────────────────────┬───────────────────────────────────┘
                           │ MessageBus (消息总线)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              WeChatOpenCode 主控核心                           │
│                                                              │
│  ┌──────────── 意图分析层 (IntentRouter) ────────────┐       │
│  │ Layer 1: / 前缀直接命令路由            (<0.1ms)    │       │
│  │ Layer 2: 句子分解 + / 前缀精确匹配                  │       │
│  │ Layer 3: LLM 意图理解 + 指令推荐       (~2s)       │       │
│  │ 兜底:  回退 Supervisor LLM 流程       (10-30s)     │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐            │
│  │ CommandHandler 体系 │  │ CronScheduler      │            │
│  │ 24个 / 命令         │  │ 中文定时任务        │            │
│  └────────────────────┘  └────────────────────┘            │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐            │
│  │ MessageBus         │  │ Context Monitor     │            │
│  │ 消息总线 (pub/sub)  │  │ 上下文自动压缩      │            │
│  └────────────────────┘  └────────────────────┘            │
└──────────────────────────┬───────────────────────────────────┘
                           │ TAG 协议通信
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──┐  ┌─────▼─────┐      │
       │Supervisor│  │  Worker   │      │
       │ 监工:4097│  │执行层:4098│      │
       │ 聊天/派活 │  │ 执行/安装  │      │
       │ 永不重启  │  │可独立重启  │      │
       └──────────┘  └───────────┘      │
                                        │
       ┌── TAG 协议通信 ────────────────┘
       │ [TASK: ...] / [进度: ...] / [结果: ...] / [FILE: ...]
```

### 消息处理全流程

```
用户消息
  │
  ├── 消息去重 ( _seen_ids 时间窗口去重)
  ├── 命令候选选择 (缩写歧义)
  ├── Worker 确认转发 (在等用户回复)
  ├── 权限检查 (危险操作需 YES 确认)
  │
  ├── / 开头 → CommandHandler (24个命令) → 直接响应
  │
  ├── [NEW] 意图分析层 (LLM 理解 + 指令推荐)
  │     ├── 匹配到命令 → 直接执行
  │     ├── 复合任务 → 步骤拆解 → 逐个执行
  │     └── 无匹配 → 回退 LLM
  │
  └── 回退到 Supervisor LLM
        ├── 普通对话 → 聊天回复
        └── [TASK: ...] → Worker 执行 → 自动发送结果文件
```

---

## 三、快速开始

### 3.1 前提条件

- Windows 10/11
- Python 3.10+
- Node.js 18+
- 飞书账号
- VC++ Redistributable（如遇 DLL 加载失败需安装）

### 3.2 安装 opencode CLI

```bash
npm install -g @opencode-ai/cli
```

### 3.3 飞书应用配置

1. 飞书开放平台 → 创建企业自建应用
2. 添加「机器人」能力
3. 事件订阅 → 使用长连接接收事件 → 添加 `im.message.receive_v1`
4. 权限管理 → 开通 `im:message:send_as_bot`、`获取用户发给机器人的消息`
5. 发布版本 → 获取 **App ID** 和 **App Secret**

### 3.4 安装

```bash
git clone <项目地址>
cd wechat-opencode
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3.5 配置

```bash
copy config.example.yaml config.yaml
# 编辑 config.yaml，填入飞书 App ID / App Secret / DeepSeek API Key
```

```yaml
bot_type: "feishu"
deepseek_api_key: "sk-..."
opencode:
  project_dir: "C:\\Users\\你的用户名"
  serve_port: 4097
  worker_serve_port: 4098
  command_timeout: 600
feishu:
  app_id: "cli_xxx"
  app_secret: "xxx"
service:
  log_level: "INFO"
  auto_restart: true
```

### 3.6 启动

```bash
python -m wechat_opencode
```

首次运行自动打开配置向导（`http://127.0.0.1:8099`）。
Web 管理面板：`http://127.0.0.1:8080`

### 3.7 环境检查

```bash
python -m wechat_opencode --check
# 检查 Node.js、opencode CLI、配置文件、API Key 等
```

---

## 四、全部指令速查

所有指令支持前缀缩写。歧义时列出候选让用户选择。

### / 命令列表

| 指令 | 缩写 | 说明 |
|------|------|------|
| **对话与任务** | | |
| 直接打字 | — | 和 AI 对话，自动分析意图分发 |
| `/plan <目标>` | — | 规划并执行任务 |
| `/tasks` | `/ta` | 任务列表 |
| `/task <N>` | — | 任务详情 |
| `/status` | `/st` | 当前状态 |
| `/cancel` | — | 三重取消（Worker + 队列 + LLM） |
| `/progress <N>` | `/pr` | 进度报告间隔(秒) |
| **定时任务** | | |
| `/cron` | — | 查看帮助 |
| `/cron add <时间> <任务>` | — | 添加定时任务 |
| `/cron list` | — | 查看所有 |
| `/cron remove <ID>` | — | 删除 |
| **上下文管理** | | |
| `/compact` | — | 压缩监工上下文 |
| `/compact all` | — | 压缩监工+执行层上下文 |
| **工具** | | |
| `/screen` | `/sc` | 截取桌面 |
| `/file <路径>` | `/f` | 搜索并发送文件 |
| `/focus <应用>` | — | 切换窗口到前台 |
| `/open <应用/文件>` | `/o` | 打开应用或文件 |
| `/desktop` | `/d` | 显示桌面 |
| `/min` `/max` | — | 最小化/最大化 |
| `/apps` | `/ap` | 列出运行中的应用 |
| `/ppt <主题>` | — | 生成 PPT |
| `/undo` | — | 撤销操作 |
| **系统** | | |
| `/model` | `/m` | 查看模型 |
| `/model flash` `/model pro` | — | 切换模型 |
| `/cost` | `/co` | 费用统计 |
| `/sessions` | `/se` | 会话列表 |
| `/new` | — | 重置会话+清空队列 |
| `/cleartasks` | — | 清空任务+清空队列 |
| `/help` | `/h` | 全部指令 |
| `/restart` | — | 重启服务 |

---

## 五、核心功能详解

### 5.1 消息总线 (MessageBus)

统一管理所有消息的发布与订阅：

- **incoming 频道**：飞书消息、Web 面板消息 → 核心处理
- **outgoing 频道**：系统回复 → 飞书发送 + Web 面板同步
- 线程安全，支持多个订阅者
- 对话历史通过总线获取，自动过滤 emoji 状态通知

### 5.2 意图分析：三层路由

| 层级 | 方式 | 速度 | 适用场景 |
|------|------|------|----------|
| Layer 1 | `/` 前缀检测 | <0.1ms | 精确命令 |
| Layer 2 | 句子分解 + / 前缀精确匹配 | <1ms | 复合任务拆解 |
| Layer 3 | LLM 意图理解 + 指令推荐 | ~2s | 自然语言需求 |
| 兜底 | 完整 LLM 流程 | 10-30s | 真正需要 AI 理解的需求 |

### 5.3 上下文自动管理

系统自动监控对话上下文使用情况：

- **自动压缩**：用户停止操作 1 小时后，且会话消息数超过 300 条，自动压缩监工和执行层的上下文
- **手动压缩**：`/compact`（仅监工）、`/compact all`（监工+执行层）
- **进度估算**：执行任务时根据 prompt 长度自动估算并显示预计时间

### 5.4 发送意图自动分解

系统检测到以下结尾词时，自动将句子拆为"前置任务 + 文件发送"两步：

| 结尾词 | 示例 | 拆解结果 |
|--------|------|----------|
| 发给我 | "把桌面来宾市简介发给我" | ① AI找文件 ② `/file` 发送 |
| 然后 | "创建文件然后发给我" | ① AI创建 ② `/file` 发送 |

### 5.5 定时任务 `/cron`

支持中文自然语言表达式：

```
/cron add 每天 09:00 发送 AI 资讯摘要
/cron add 每30分钟 检查服务器磁盘
/cron add 周一到周五 08:00 生成日报
```

| 格式 | 示例 |
|------|------|
| `每天 HH:MM` | `每天 09:00` |
| `每N分钟` / `每N小时` | `每30分钟` `每2小时` |
| `周一到周五 HH:MM` | `周一到周五 08:00` |
| `工作日 HH:MM` | `工作日 09:30` |

### 5.6 文件传输 `/file`

- **明确路径**：`/file C:/Users/1/Desktop/报告.docx` → 直接发送
- **模糊描述**：`/file 配置文件` → AI 引导找到文件
- **自动发现**：Worker 输出中的 `[FILE: 路径]` 标签自动提取并发送（去重）

### 5.7 PPT 生成 `/ppt`

- 自动启动 PPT 设计师 Worker
- 第一步：让用户确认参数（主题、风格、页数）
- 生成文件默认保存到桌面
- 支持 python-pptx 专业模板（5 套配色主题）

### 5.8 自扩展能力（Worker）

Worker 执行任务时具备自扩展能力：

- 缺工具自动 pip/npm install
- 能力寻路链：搜索→安装→换方法→最终确认
- 永不放弃：尝试 3 种以上方案再汇报失败

### 5.9 自愈机制

| 机制 | 实现 |
|------|------|
| 自动重试 ×3 | 第1次立即重试 → 第2次换参数 → 第3次换工具 |
| Git 回滚 | 任务执行前 checkpoint，失败时自动恢复 |
| send_text 重试 | 网络错误时自动重试 1 次 |
| Worker 无响应 | 10分钟无新消息 → 自动终止 |
| 消息去重 | 时间窗口去重，自动清理过期条目 |

---

## 六、系统组件详解

### 6.1 意图路由器 (intent_router.py)

```
analyze(text, session=None) → IntentResult
  ├── type="command"  → 匹配到内置指令，直接执行
  ├── type="compound" → 多步骤任务，逐个执行
  ├── type="chat"     → 普通对话，回退 LLM
  └── type="task"     → 单步骤任务，需要 LLM
```

### 6.2 命令处理器 (commands/)

24 个 / 命令均由独立 Handler 类处理：

| 文件 | 命令 |
|------|------|
| `help.py` | help |
| `screen.py` | screen |
| `window.py` | desktop, min, max, apps, focus, open |
| `file.py` | file |
| `session.py` | sessions, new |
| `task.py` | tasks, task, cancel, cleartasks |
| `status.py` | status, progress, cost |
| `model.py` | model |
| `ppt.py` | ppt |
| `undo.py` | undo |
| `system.py` | restart, compact, cron |
| `plan.py` | plan |

### 6.3 消息总线 (bus.py)

```
MessageBus
  ├── publish(channel, msg)  → 发布消息到频道
  ├── subscribe(channel, cb) → 订阅频道
  ├── get_messages()         → 获取增量消息（供 Web 面板轮询）
  ├── get_history()          → 获取对话历史（供 LLM 上下文注入）
  └── last_id                → 最新消息 ID
```

### 6.4 异常体系 (exceptions.py)

```
WOCError                    ← 基类
├── BotError                ← 机器人连接错误
├── ConfigError             ← 配置错误
├── SessionError            ← 会话错误
├── WorkerError             ← 执行错误
├── PermissionDenied        ← 权限拒绝
└── ExecutionTimeout        ← 执行超时
```

---

## 七、TAG 协议（内部通信）

监工和执行层之间通过严格正则匹配的纯文本标签通信：

| 标签 | 方向 | 含义 |
|------|------|------|
| `[TASK: 描述]` | 监工→Worker | 分配任务 |
| `[进度: 步骤N/M ...]` | Worker→监工 | 进度汇报 |
| `[确认: 问题]` | Worker→用户 | 需要确认 |
| `[结果: 成功 ...]` | Worker→监工 | 任务完成 |
| `[结果: 失败 ...]` | Worker→监工 | 任务失败 |
| `[FILE: 路径]` | Worker→系统 | 文件产物标记 |
| `[CANCEL]` | 任意方向 | 取消 |

---

## 八、配置文件

### config.yaml

```yaml
bot_type: "feishu"
deepseek_api_key: "sk-..."
opencode:
  project_dir: "C:\\Users\\你的用户名"
  serve_port: 4097
  worker_serve_port: 4098
  serve_host: "127.0.0.1"
  command_timeout: 600
feishu:
  app_id: "cli_xxx"
  app_secret: "xxx"
service:
  heartbeat_interval: 30
  auto_restart: true
  log_level: "INFO"
  log_file: "wechat_opencode.log"
```

---

## 九、Web 管理面板

`http://127.0.0.1:8080`

- 实时聊天界面（与飞书消息同步，通过消息总线驱动）
- 当前任务状态（空闲/执行中）
- 模型信息
- 快捷按钮（截图/费用/任务/模型切换）
- 暗色模式
- 对话导出（Markdown）
- Worker 日志查看

---

## 十、常见问题

**Q: opencode CLI 未找到？**

运行 `python -m wechat_opencode` 前需要先安装：
```bash
npm install -g @opencode-ai/cli
```
需要 Node.js 18+。

**Q: pip install 报 SSL 错误？**

网络环境无法直连 pypi.org，请使用国内镜像源：
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q: 自然语言指令没有被正确识别？**

Layer 3 (LLM 分类) 需要 1-2 秒。如果长时间无响应，检查网络连接和 DeepSeek API Key。

**Q: 任务阻塞？**

使用 `/cancel` 三重取消（Worker + 队列 + 当前执行），或 `/new` 重置。

**Q: 定时任务不执行？**

用 `/cron list` 检查任务是否成功创建。

**Q: 飞书连接失败？**

检查 App ID/Secret，确认应用已发布，检查网络能否解析 `open.feishu.cn`。

---

## 十一、版本历史

| 日期 | 更新 |
|------|------|
| 2026-06-16 | **消息总线**: 统一管理所有消息流，飞书 + Web 同步 |
| 2026-06-16 | **上下文自动管理**: 1 小时空闲自动压缩 + `/compact all` |
| 2026-06-16 | **进度估算**: 执行任务时显示预计耗时 |
| 2026-06-16 | **send_text 重试**: 网络错误自动重试 |
| 2026-06-16 | **意图路由器增强**: LLM 理解 + 指令推荐，去自然语言关键词 |
| 2026-06-16 | **Session 复用**: 不再重复创建监工 session |
| 2026-06-16 | **抢占上下文**: 被取消的消息内容传递给下一条 |
| 2026-06-16 | **步骤清洗**: 复合任务分解过滤多余标点 |
| 2026-06-14 | 定时任务系统 (`/cron` + CronScheduler) |
| 2026-06-14 | 24个命令的 CommandHandler 体系 |
| 2026-06-14 | 双 serve 架构 + 文件传递 + 指令缩写系统 |

---

*文档版本: 2026-06-16*
