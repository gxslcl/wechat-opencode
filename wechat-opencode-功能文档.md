# WeChat-OpenCode 功能文档与操作手册

> 版本: 2026-06-14 | 意图路由器 | 三层分析 | 自动拆解 | 定时任务 | 群聊支持

---

## 一、项目概述

**WeChat-OpenCode** 是一个将飞书消息桥接到 OpenCode AI 的智能机器人。用户通过飞书向机器人发送指令，机器人理解需求并自动执行——操作电脑、编写代码、管理文件、生成 PPT 等。

**核心理念**: 用聊天的方式操控电脑。

### 核心创新：意图路由器

传统的 AI 助手对话：用户说一句话 → 全部送交 LLM → 等待回复（慢且贵）。

**WeChat-OpenCode 的意图路由器**：先分析这句话能不能用内置指令直接完成，能就不用 LLM。

```
用户: "把桌面来宾市简介发给我"
  ↓ 意图路由器分析
  ① "把桌面来宾市简介" → 无匹配指令 → 交给 AI 执行
  ② "发给我" → 匹配 /file 指令 → 直接发送文件 (0 LLM调用)
```

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     用户 (飞书)                                │
│  私聊 / 群聊 @机器人                                           │
└──────────────────────────┬───────────────────────────────────┘
                           │ WebSocket 长连接
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     FeishuBot                                 │
│  · 接收文字/图片/文件   · 发送文本/卡片/文件/图片              │
│  · 群聊 @机器人 触发     · 消息编辑实时更新进度                │
│  · 消息去重 (10条窗口)   · 图片下载转换为文件路径              │
└──────────────────────────┬───────────────────────────────────┘
                           │ WxMessage
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              WeChatOpenCode 主控核心                           │
│                                                              │
│  ┌──────────── 意图分析层 (IntentRouter) ────────────┐       │
│  │ Layer 1: / 前缀直接命令路由            (<0.1ms)    │       │
│  │ Layer 2: 60+关键词 + 发送意图分解      (<1ms)      │       │
│  │ Layer 3: 轻量 LLM JSON 分类           (~2s)       │       │
│  │ 兜底:  回退主 LLM 流程                (保持原样)    │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐            │
│  │ CommandHandler 体系 │  │ CronScheduler      │            │
│  │ 24个 / 命令         │  │ 中文定时任务        │            │
│  └────────────────────┘  └────────────────────┘            │
└──────────────────────────┬───────────────────────────────────┘
                           │
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
  ├── 消息去重 (_seen_ids 2000条)
  ├── 命令候选选择 (缩写歧义)
  ├── Worker 确认转发 (在等用户回复)
  ├── 权限检查 (危险操作需 YES 确认)
  │
  ├── / 开头 → CommandHandler (24个命令) → 直接响应
  │
  ├── [NEW] 意图分析层
  │     ├── 匹配到命令 → 直接执行 (0 LLM)
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

### 3.2 飞书应用配置

1. 飞书开放平台 → 创建企业自建应用
2. 添加「机器人」能力
3. 事件订阅 → 使用长连接接收事件 → 添加 `im.message.receive_v1`
4. 权限管理 → 添加 `im:message:send_as_bot`、`获取用户发给机器人的消息`
5. 发布版本 → 获取 **App ID** 和 **App Secret**

### 3.3 安装

```bash
git clone <项目地址>
cd wechat-opencode
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install schedule      # 定时任务支持
```

### 3.4 配置

编辑 `config.yaml`：

```yaml
bot_type: "feishu"
opencode:
  project_dir: "C:\\Users\\你的用户名"
  serve_port: 4097
  worker_serve_port: 4098
  command_timeout: 300
feishu:
  app_id: "cli_xxx"
  app_secret: "xxx"
service:
  log_level: "INFO"
  auto_restart: true
```

### 3.5 启动

```bash
python -m wechat_opencode
```

首次运行自动打开配置向导（`http://127.0.0.1:8099`）。
Web 管理面板：`http://127.0.0.1:8080`

---

## 四、全部指令速查

所有指令支持前缀缩写。歧义时列出候选让用户选择。

### 自然语言识别（无需 / 前缀）

| 你说的话 | 系统理解 | 执行 |
|----------|---------|------|
| "截图" "截个屏" | → `/screen` | 直接截图发飞书 |
| "显示桌面" | → `/desktop` | 最小化所有窗口 |
| "费用" "花了多少" | → `/cost` | 显示费用统计 |
| "把X发给我" | → 自动拆解: AI做X + `/file` 发送 | 复合执行 |
| "切换到 Chrome" | → `/focus Chrome` | 窗口切换 |

### / 命令列表

| 指令 | 缩写 | 说明 |
|------|------|------|
| **对话与任务** | | |
| 直接打字 | — | 和 AI 对话，自动分析意图分发 |
| `/plan <目标>` | — | 规划并执行任务 |
| `/tasks` | `/ta` | 任务列表 |
| `/task <N>` | — | 任务详情 |
| `/status` | `/st` | 当前状态 |
| `/cancel` | — | 取消任务 + 清空队列 + 中断执行 |
| `/progress <N>` | `/pr` | 进度报告间隔(秒) |
| **定时任务** ⭐ | | |
| `/cron` | — | 查看帮助 |
| `/cron add <时间> <任务>` | — | 添加定时任务 |
| `/cron list` | — | 查看所有 |
| `/cron remove <ID>` | — | 删除 |
| **工具** | | |
| `/screen` | `/sc` | 截取桌面 |
| `/file <路径>` | `/f` | 搜索并发送文件 |
| `/focus <应用>` | — | 切换窗口到前台 |
| `/open <应用/文件>` | `/o` | 打开应用或文件 |
| `/desktop` | `/d` | 显示桌面 |
| `/min` `/max` | — | 最小化/最大化 |
| `/apps` | `/ap` | 列出运行中的应用 |
| `/ppt <主题>` | — | 生成 PPT |
| `/undo` | — | 撤销操作(恢复文件) |
| **系统** | | |
| `/model` | `/m` | 查看模型 |
| `/model flash` `/model pro` | — | 切换模型 |
| `/cost` | `/co` | 费用统计 |
| `/sessions` | `/se` | 会话列表 |
| `/new` | — | 重置会话+清空队列 |
| `/compact` | — | 压缩上下文 |
| `/cleartasks` | — | 清空任务+清空队列 |
| `/help` | `/h` | 全部指令 |
| `/restart` | — | 重启服务 |

---

## 五、核心功能详解

### 5.1 意图分析：自然语言自动路由

**三层分析机制**：

| 层级 | 方式 | 速度 | 适用场景 |
|------|------|------|----------|
| Layer 1 | `/` 前缀检测 | <0.1ms | 精确命令 |
| Layer 2 | 关键词模式匹配 + 发送意图分解 | <1ms | 自然语言指令 |
| Layer 3 | 轻量 LLM JSON 分类 | ~2s | 关键词未命中的复杂意图 |
| 兜底 | 完整 LLM 流程 | 5-30s | 真正需要 AI 理解的需求 |

**发送意图自动分解**：

系统检测到以下结尾词时，自动将句子拆为"前置任务 + 文件发送"两步：

| 结尾词 | 示例 | 拆解结果 |
|--------|------|----------|
| 发给我 | "把桌面来宾市简介发给我" | ① AI找文件 ② `/file` 发送 |
| 发我 | "写个报告发我" | ① AI写报告 ② `/file` 发送 |
| 发过来 | "截图发过来" | ① `/screen` ② `/file` 发送 |
| 传给我 | "把C盘的文件传给我" | ① AI找文件 ② `/file` 发送 |
| 发到飞书 | "创建文档然后发送到飞书" | ① AI创建 ② `/file` 发送 |
| 发一份给我 | "整理数据发一份给我" | ① AI整理 ② `/file` 发送 |

**分离词拆解**：

| 分离词 | 示例 |
|--------|------|
| 然后 | "创建文件然后发给我" → 2步 |
| 之后 | "分析代码之后运行测试" → 2步 |
| 接着 | "安装依赖接着启动服务" → 2步 |
| 再 / 最后 / 并且 | 同理拆解 |

### 5.2 定时任务 `/cron`

支持中文自然语言表达式：

```
/cron add 每天 09:00 发送 AI 资讯摘要
/cron add 每30分钟 检查服务器磁盘
/cron add 周一到周五 08:00 生成日报
/cron add 每2小时 同步代码仓库
```

| 格式 | 示例 |
|------|------|
| `每天 HH:MM` | `每天 09:00` |
| `每N分钟` / `每N小时` | `每30分钟` `每2小时` |
| `每隔N分钟/小时` | `每隔15分钟` |
| `周一到周五 HH:MM` | `周一到周五 08:00` |
| `工作日 HH:MM` | `工作日 09:30` |
| `周一 HH:MM` ~ `周日 HH:MM` | `周五 17:00` |

### 5.3 取消与清空

`/cancel` 现在执行三重取消：
1. 取消 Worker 正在执行的任务
2. 清空 Supervisor 队列中所有待执行命令
3. 中断 Supervisor 当前 LLM 调用

`/cleartasks` 同步清空任务记录 + 队列中的待执行命令。

`/new` 重置会话时同步清空队列。

### 5.4 文件传输 `/file`

**明确路径**（立即发送）：
```
/file C:/Users/1/Desktop/报告.docx
→ 📎 发送文件: 报告.docx (156KB)
```

**模糊描述**（AI 交互）：
```
/file 配置文件
→ AI 引导你逐步找到文件
```

**自动文件发现** ⭐：
Worker LLM 执行任务后，系统自动扫描输出中的 `[FILE: 路径]` 标签，
自动将发现的文件发送到飞书，无需用户手动操作。

### 5.5 飞书消息卡片

执行结果以结构化卡片展示：

| 卡片类型 | 用途 |
|----------|------|
| 结果卡片 | 绿色头(成功)/红色头(失败) + 耗时 + 费用 + 输出 |
| 进度卡片 | 蓝色头 + 任务名 + 进度 + 耗时 |
| 状态卡片 | 当前 Supervisor + Worker 状态 |
| 帮助卡片 | 全部指令一览 |

### 5.6 消息编辑实时进度

Worker 执行期间，进度消息使用飞书编辑功能**同一条消息持续更新**，不会刷屏。

### 5.7 群聊支持

在飞书群聊中 `@机器人 指令`，系统自动识别并处理。
非 @机器人的消息会被忽略。

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

关键函数：
- `match_command(text)` — 60+ 关键词 → /指令 映射
- `decompose_with_send_intent(text)` — 发送意图分解
- `extract_artifacts(output)` — LLM 输出中提取文件路径
- `parse_classification_output(json)` — Layer 3 LLM 结果解析

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

### 6.3 定时任务系统 (scheduler.py)

```
CronScheduler
  ├── add_job(表达式, 任务) → 创建定时任务
  ├── remove_job(ID) → 删除
  ├── list_jobs() → 查看所有
  └── _parse_schedule(中文表达式) → (间隔, 单位, 时间点)
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

### 6.5 自动恢复机制

| 机制 | 实现 |
|------|------|
| 自动重试 ×3 | Worker 第1次立即重试 → 第2次换参数 → 第3次换工具 |
| Git 回滚 | 任务执行前 checkpoint，失败时自动恢复 |
| Worker 无响应 | 10分钟无新消息 → 自动终止 |
| 执行超时 | 30分钟强制终止 |
| 源码热重载 | AutoReloader 3秒轮询 → 自动重启 |
| 消息去重 | 飞书侧10条 + 全局2000条 |

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

TAG 匹配使用行首锚定正则 (`^\[TASK:`)，避免对话中出现 `[TASK:` 字符串时的误匹配。

---

## 八、配置文件

### config.yaml

```yaml
bot_type: "feishu"
opencode:
  project_dir: "C:\\Users\\你的用户名"
  serve_port: 4097
  worker_serve_port: 4098
  serve_host: "127.0.0.1"
  command_timeout: 300
feishu:
  app_id: "cli_xxx"
  app_secret: "xxx"
service:
  heartbeat_interval: 30
  auto_restart: true
  log_level: "INFO"
  log_file: "wechat_opencode.log"
```

### opencode.json

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "deepseek/deepseek-chat",
  "mcp": {
    "playwright": {
      "type": "local", "enabled": true,
      "command": "npx", "args": ["-y", "@playwright/mcp"]
    },
    "filesystem": {
      "type": "local", "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\1"]
    }
  }
}
```

---

## 九、Web 管理面板

`http://127.0.0.1:8080`

- 实时聊天界面（与飞书消息同步）
- 当前任务状态（空闲/执行中）
- 模型信息
- 快捷按钮（截图/费用/任务/模型切换）
- 暗色模式
- 对话导出（Markdown）
- Worker 日志查看

---

## 十、常见问题

**Q: 自然语言指令没有被正确识别？**

检查日志中是否有 "Intent matched" 行。如果走到 Layer 3 (LLM分类)，可能需要 1-2 秒。
如果完全没有匹配，说明当前 60+ 关键词库里没有对应模式。

**Q: 任务阻塞？**

使用 `/cancel` 三重取消（Worker + 队列 + 当前执行），或 `/new` 重置。
发送新消息时如果 Worker 正在运行，会自动取消当前任务。

**Q: 定时任务不执行？**

确认安装了 `schedule` 包（`pip install schedule`）。
用 `/cron list` 检查任务是否成功创建。

**Q: 文件传输找不到文件？**

用明确路径：`/file C:/Users/1/Desktop/文件名.docx`
或用自然语言描述，AI 会引导查找。

---

## 十一、版本历史

| 日期 | 更新 |
|------|------|
| 2026-06-14 | **意图路由器**: 三层分析 + 发送意图自动分解 + LLM 产物自动发送 |
| 2026-06-14 | 复合任务顺序执行 + artifacts 上下文传递 |
| 2026-06-14 | `/cancel` 三重取消(Worker + 队列 + 当前执行) |
| 2026-06-14 | `/cleartasks` `/new` 同步清空队列 |
| 2026-06-14 | 定时任务系统 (`/cron` + CronScheduler) |
| 2026-06-14 | 飞书消息卡片输出 (ResultFormatter) |
| 2026-06-14 | 消息编辑实时进度 (FeishuBot.edit_message) |
| 2026-06-14 | 群聊 @机器人 支持 |
| 2026-06-14 | TAG 严格正则 (避免误匹配) |
| 2026-06-14 | 24个命令的 CommandHandler 体系 |
| 2026-06-14 | BotABC 抽象接口 + 统一异常体系 |
| 2026-05-24 | 双 serve 架构 + 文件传递 + 指令缩写系统 |

---

*文档版本: 2026-06-14 | 项目路径: C:\Users\1\wechat-opencode*
