# WeChat-OpenCode 功能文档与操作手册

> 版本: 2026-05-24 | 双 serve 架构 | 飞书/微信双端支持

---

## 一、项目概述

**WeChat-OpenCode** 是一个将微信/飞书消息桥接到 OpenCode AI 的智能机器人。用户通过飞书或微信向机器人发送指令，机器人调用 AI 大模型理解需求并自动执行任务——操作电脑、编写代码、管理文件、生成 PPT 等。

**核心理念**: 用聊天的方式操控电脑。

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────┐
│                      用户 (飞书/微信)                      │
└────────────┬──────────────────────────────┬──────────────┘
             │                              │
      ┌──────▼──────┐               ┌──────▼──────┐
      │ FeishuBot   │               │ WeChatBridge│
      │ (飞书机器人) │               │ (微信桥接)   │
      └──────┬──────┘               └──────┬──────┘
             │                              │
             └──────────┬───────────────────┘
                        │ WxMessage
                 ┌──────▼──────┐
                 │ MessageRouter│  (检查 /oc 前缀)
                 └──────┬──────┘
                        │ Command
                 ┌──────▼──────────────┐
                 │  WeChatOpenCode      │
                 │  (主控核心)          │
                 │                      │
                 │  ┌────────────────┐  │
                 │  │ 元命令处理      │  │  /stop /help /screen /file ...
                 │  │ (不经过LLM)     │  │
                 │  └────────────────┘  │
                 │  ┌────────────────┐  │
                 │  │ ExecutionQueue │  │  顺序执行
                 │  └───────┬────────┘  │
                 └──────────┼───────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
   ┌──────▼──────┐  ┌──────▼──────┐          │
   │ Supervisor  │  │   Worker    │          │
   │ 监工 :4097  │  │ 执行层 :4098│          │
   │             │  │             │          │
   │ 聊天/派活    │  │ 安装/执行   │          │
   │ 无 MCP      │  │ 有 MCP/Skill│          │
   │ 永远不重启   │  │ 可独立重启   │          │
   └─────────────┘  └─────────────┘          │
                                             │
       双 serve 架构: 监工和执行层分离         │
       各自独立端口, Worker 装 MCP 时可独立重启  │
```

### 双 Serve 架构详解

| 组件 | 端口 | 功能 | MCP/Skill | 重启影响 |
|------|------|------|-----------|----------|
| Supervisor (监工) | 4097 | 理解需求、分配任务、聊天 | 无 | 重启会丢失会话 |
| Worker (执行层) | 4098 | 执行具体任务、安装软件包 | 全部 MCP/Skill | 可随时独立重启 |

**关键优势**: Worker 安装新的 MCP 服务器或 Skill 后，只需重启 4098 端口的 Worker serve，监工不受影响。

---

## 三、快速开始

### 3.1 配置文件 (config.yaml)

```yaml
# 机器人后端: "wechat" 或 "feishu"
bot_type: "feishu"

opencode:
  project_dir: "C:\\Users\\1"          # 工作目录
  serve_port: 4097                      # 监工端口
  worker_serve_port: 4098              # 执行层端口
  serve_host: "127.0.0.1"
  command_timeout: 300                  # 命令超时(秒)

wechat:
  prefix: "/oc"                         # 微信触发前缀
  bot_remark: "机器人"                   # 机器人备注名

feishu:
  app_id: "cli_xxx"                     # 飞书应用 ID
  app_secret: "xxx"                     # 飞书应用密钥

service:
  heartbeat_interval: 30
  auto_restart: true
  log_level: "INFO"
  log_file: "wechat_opencode.log"
```

### 3.2 启动方式

```bash
# 正常启动
python -m wechat_opencode

# 或使用启动脚本
start.bat

# 干跑模式（不实际启动 opencode serve）
start_dryrun.bat
```

### 3.3 使用方式

| 平台 | 触发方式 |
|------|----------|
| 飞书 | 直接在对话中发送指令（无需前缀） |
| 微信 | 发送 `/oc` 开头的消息（如 `/oc 你好`） |

---

## 四、全部指令速查

### 4.1 指令缩写系统

所有指令支持前缀缩写。例如 `/m` → `/model`，`/h` → `/help`。当缩写有歧义时（如 `/s` 匹配 screen/sessions/status/stop），系统会列出候选让你选择。

| 指令 | 缩写 | 说明 |
|------|------|------|
| `/help` | `/h` | 查看帮助 |
| `/stop` | — | 关闭服务 |
| `/new` | — | 新建执行会话（`/fresh` 同义） |
| `/model` | `/m` | 查看/切换模型 |
| `/model flash` | `/m f` | 切换到 flash 模型 |
| `/model pro` | `/m p` | 切换到 pro 模型 |
| `/screen` | `/sc` | 截取电脑桌面 |
| `/ppt <主题>` | — | 生成 PPT |
| `/undo` | — | 撤销上次操作 |
| `/cancel` | — | 取消执行中的任务 |
| `/status` | `/st` | 查看当前任务状态 |
| `/plan <目标>` | — | 规划并执行任务 |
| `/tasks` | `/ta` | 查看任务列表 |
| `/task <N>` | — | 查看第 N 个任务详情 |
| `/sessions` | `/se` | 查看执行会话列表 |
| `/1` `/2` `/3` | — | 切换到第 N 个执行会话 |
| `/cost` | `/co` | 查看费用统计 |
| `/file <路径>` | `/f` | 搜索并发送文件 |

---

## 五、指令详细说明

### 5.1 对话与任务

**任意文字**（不以 `/` 开头）直接发送给监工 AI 对话。监工会理解你的需求，必要时自动分配任务给执行层。

```
用户: 帮我把桌面整理一下
监工: [TASK: 整理桌面文件，按类型分类到文件夹]
Worker: [进度: 正在扫描桌面...]
Worker: [结果: 成功 已将 15 个文件分类到 4 个文件夹]
```

### 5.2 模型切换 `/model`

```
/model          → 查看当前模型
/model flash    → 切换到 deepseek-chat (快速)
/model pro      → 切换到 deepseek-v4-pro (高能力)

简写: /m flash, /m pro
```

### 5.3 截图 `/screen`

截取电脑桌面截图并发送给你。

```
/screen
→ 📸 正在截图...
→ [桌面截图]
```

### 5.4 文件传递 `/file` ⭐ 新功能

**两种模式**:

#### 模式 1: 明确路径（立即发送）

```
/file C:/Users/1/Desktop/报告.docx
→ 📎 发送文件: 报告.docx (156.3KB)
→ [文件消息]
```

如果路径不存在，自动转交监工 AI 帮你找。

#### 模式 2: 模糊描述（AI 交互查找）

```
/file 配置文件
→ 🔍 正在帮你找文件: 配置文件

监工: 请问文件大概在哪个目录？
  1. 桌面
  2. 下载
  3. 文档
  4. D盘
  5. E盘
  6. 微信接收文件
  7. 其他

用户: 1

监工: 桌面文件列表:
  1. 报告.docx (156KB)
  2. config.yaml (2KB)
  ...

用户: 2
→ 📎 发送文件: config.yaml (2KB)
```

### 5.5 PPT 生成 `/ppt`

```
/ppt AI发展趋势
→ 🎨 PPT 设计师已就位
Worker: 生成包含标题页、目录、5个内容页、总结页的PPT
→ [PPT 文件]
```

### 5.6 规划执行 `/plan`

将目标分解为步骤逐步执行，遇到错误自动修复。

```
/plan 帮我搭建一个 Flask Web 项目
→ 🎯 规划任务: 帮我搭建一个 Flask Web 项目
Worker: 1.安装Flask 2.创建app.py 3.创建模板 4.测试运行
```

### 5.7 任务管理

```
/tasks          → 查看最近 10 个任务列表
/task 3         → 查看第 3 个任务详情（含执行步骤）
/status         → 查看当前执行状态
/cancel         → 取消正在执行的任务
```

### 5.8 会话管理

```
/sessions       → 查看最近 10 个执行会话
/1 /2 /3        → 切换到指定会话（继续之前的对话）
/new            → 重置为全新会话
```

### 5.9 其他工具

```
/undo           → 撤销上一步操作（恢复代码文件）
/cost           → 查看 API 调用费用统计
/stop           → 关闭机器人服务
```

---

## 六、协议标签（内部通信）

监工和执行层之间通过以下标签通信，用户可在回复中看到：

| 标签 | 方向 | 含义 |
|------|------|------|
| `[TASK: ...]` | 监工→执行 | 分配任务 |
| `[进度: ...]` | 执行→监工 | 进度汇报 |
| `[确认: ...]` | 执行→用户 | 需要用户选择 |
| `[结果: 成功 ...]` | 执行→监工 | 任务完成 |
| `[结果: 失败 ...]` | 执行→监工 | 任务失败 |
| `[CANCEL]` | 任意 | 取消操作 |
| `[FILE: 路径]` | 监工→系统 | 触发文件发送 |

---

## 七、文件传输功能详解

### 7.1 三层搜索架构

```
/file <query>
    │
    ├─ 绝对路径 (C:/.../file.docx)
    │   ├─ 文件存在 → 直接发送
    │   └─ 不存在 → 转交 AI 交互查找
    │
    └─ 模糊描述 (配置文件)
        └─ 转交监工 AI 三步交互:
           ① 询问文件位置（桌面/下载/D盘...）
           ② 列出选中目录文件（带编号，按时间排序）
           ③ 用户选编号 → [FILE: 路径] → 发送
```

### 7.2 中文关键词映射

文件搜索支持中文关键词自动展开：

| 中文 | 自动搜索 |
|------|----------|
| 配置/设置 | config, settings, .env |
| 日志 | log, logger, logging |
| 测试 | test, tests, spec |
| 文档/说明 | doc, readme, guide |
| 接口/路由 | api, router, route |
| 前端 | ui, template, components |
| 后端 | api, server, service |
| 数据库 | db, database, sql, schema |
| 截图/图片 | screenshot, image, capture |

### 7.3 安全机制

- 搜索深度限制: 最多 5 层子目录
- 文件数上限: 8000 个后停止
- 超时保护: 10 秒自动中断
- 跳过系统目录: AppData, .git, node_modules 等
- 敏感文件过滤: .env, 私钥, 证书等不发送

---

## 八、配置参考

### 完整配置项

| 配置路径 | 默认值 | 说明 |
|----------|--------|------|
| `bot_type` | `"wechat"` | 机器人类型: wechat / feishu |
| `opencode.project_dir` | `C:\Users\<用户名>` | 工作目录 |
| `opencode.serve_port` | `4096` | 监工端口 |
| `opencode.worker_serve_port` | `4098` | 执行层端口 ⭐ 新增 |
| `opencode.serve_host` | `127.0.0.1` | 服务地址 |
| `opencode.command_timeout` | `300` | 命令超时(秒) |
| `wechat.prefix` | `"/oc"` | 微信触发前缀 |
| `wechat.filehelper_wxid` | `"filehelper"` | 微信文件助手 |
| `wechat.bot_remark` | `"机器人"` | 机器人备注名 |
| `wechat.max_message_length` | `4000` | 单条消息最大字符数 |
| `wechat.max_parts` | `10` | 拆分最大条数 |
| `feishu.app_id` | `""` | 飞书应用 ID |
| `feishu.app_secret` | `""` | 飞书应用密钥 |
| `service.heartbeat_interval` | `30` | 心跳间隔(秒) |
| `service.auto_restart` | `true` | 异常自动重启 |
| `service.log_level` | `"INFO"` | 日志级别 |
| `service.log_file` | `"wechat_opencode.log"` | 日志文件名 |

---

## 九、MCP 和 Skill 管理

### 安装 MCP 服务器

MCP 服务器配置在 `opencode.json` 中。当前已安装：

```json
{
  "mcp": {
    "playwright": {   // 浏览器自动化
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@playwright/mcp"]
    },
    "filesystem": {   // 文件系统操作
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\1"]
    }
  }
}
```

### 添加新 MCP

1. 告诉机器人："帮我安装 XXX MCP 服务器"
2. 执行层会自动修改 `opencode.json`
3. 执行层 serve (:4098) 会自动重启生效
4. 监工 serve (:4097) 不受影响

### 自动重载

- AutoReloader 每 3 秒检测 `wechat_opencode/` 目录下的 `.py` 文件变化
- 检测到变化后，如果执行层正在忙碌，会**推迟重启**直到任务完成
- 监工在重启期间保持运行（双 serve 架构的保护机制）

---

## 十、Web 管理界面

启动后自动开启 Web 管理界面: `http://127.0.0.1:8080`

提供：
- 当前任务状态监控
- 执行历史查看
- 费用统计
- 模型信息

---

## 十一、常见问题

### Q: 为什么发送指令后没有回应？

1. 检查日志 `wechat_opencode.log` 查看错误
2. 确认 opencode serve 正常运行（端口 4097/4098）
3. 飞书模式确认网络连接正常
4. 微信模式确认 `/oc` 前缀正确

### Q: 指令缩写不生效？

确认指令在支持列表中（`/help` 查看全部指令）。部分指令如 `/stop` 没有缩写（避免误触发）。

### Q: 如何让机器人学习新能力？

直接告诉它需求，执行层会自动安装需要的工具包。例如：
> "帮我安装一个处理 Excel 的 MCP 服务器"

执行层会安装并配置好。

### Q: 文件传输找不到文件？

1. 用明确路径：`/file C:/Users/1/Desktop/文件名.docx`
2. 用自然语言描述，AI 会引导你逐步找到

---

## 十二、版本历史

| 日期 | 更新 |
|------|------|
| 2026-05-24 | 双 serve 架构（监工:4097 + 执行层:4098） |
| 2026-05-24 | 文件传递功能 `/file`（三层交互） |
| 2026-05-24 | 指令缩写系统（前缀匹配 + 歧义候选） |
| 2026-05-24 | AutoReloader 任务保护（忙碌时推迟重启） |
| 之前 | 监工/执行层分离、PPT 生成、截图、撤销等 |

---

*文档自动生成于 2026-05-24 | 项目路径: C:\Users\1\wechat-opencode*
