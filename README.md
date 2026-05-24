# 🖥️ WeChat-OpenCode

**用聊天操控电脑的 AI 管家** — 通过飞书或微信向你的电脑发送指令，AI 自动执行。

```
手机发: "帮我写个爬虫抓取天气数据"
  → 监工理解需求 → 执行层写代码 → 测试 → 结果发回手机
```

## 能力一览

| 类别 | 功能 |
|------|------|
| 💬 对话 | 自然语言聊天，AI 理解需求自动执行 |
| 💻 编程 | 写代码、修 bug、搭项目、跑测试 |
| 🖥️ 操控 | 截图、窗口管理、打开应用、文件传递 |
| 📦 扩展 | 支持 MCP 协议，可装任意插件 |
| 🔄 自愈 | 任务失败自动重试 3 次 + 自动回滚 |
| 📊 监控 | Web 管理面板 + 进度报告 + 费用追踪 |
| 📱 移动 | 微信/飞书随时发指令，手机就是终端 |

## 系统架构

```
你的手机 (飞书/微信)
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

## 快速开始

### 前提条件

- Windows 10/11
- Python 3.10+
- Node.js 18+（OpenCode CLI 依赖）
- 飞书账号（用于创建机器人）

### 1. 安装

```bash
# 克隆项目
git clone https://github.com/yourname/wechat-opencode.git
cd wechat-opencode

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 准备工作

**获取 DeepSeek API Key：**
1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 注册 → API Keys → 创建 → 复制 `sk-...`

**创建飞书机器人：**
1. 访问 [飞书开放平台](https://open.feishu.cn/app)
2. 创建企业自建应用 → 添加「机器人」能力
3. 复制 **App ID** 和 **App Secret**
4. 在「权限管理」中开通：`im:message:send_as_bot`、`获取用户发给机器人的消息`
5. 发布版本 → 等待审核通过

### 3. 启动

```bash
python -m wechat_opencode
```

首次运行会自动打开配置向导，按提示填入：
- DeepSeek API Key
- 飞书 App ID + App Secret
- 选择模型（Flash / Pro）

配置完成后服务自动启动，浏览器打开 `http://127.0.0.1:8080` 管理面板。

### 4. 开始使用

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
| `/compact` | — | 压缩对话上下文 |
| `/cleartasks` | — | 清空任务记录 |
| `/restart` | — | 重启服务 |

> 所有指令支持前缀缩写。如 `/m` → `/model`，`/sc` → `/screen`。歧义时自动列出候选。

## 配置文件

首次启动后自动生成 `config.yaml`：

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
  heartbeat_interval: 30
  auto_restart: true
  log_level: "INFO"
```

## 扩展能力

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
cat wechat_opencode.log
```

**常见问题：**
- 飞书连接失败 → 检查 App ID/Secret，确认应用已发布
- 指令无响应 → 检查 `DEEPSEEK_API_KEY` 环境变量
- Web 面板打不开 → 确认端口 8080 未被占用

## 开发

```bash
pip install -r requirements.txt
pytest tests/          # 141 个测试
python -m wechat_opencode --dry-run  # 不启动服务，仅测试
```

## License

MIT
