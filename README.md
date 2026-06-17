# WeChat-OpenCode

**用聊天操控电脑的 AI 管家** — 通过飞书向电脑发送指令，AI 自动执行。

## 能力一览

| 类别 | 功能 |
|------|------|
| 意图识别 | 三层分析：/前缀命令 → LLM 分类，自动路由 |
| 任务拆解 | 复合任务自动拆解为步骤，逐步执行 |
| 编程 | 写代码、修 bug、搭项目、跑测试 |
| 操控 | 截图、窗口管理、打开应用、文件传递 |
| 定时 | 中文表达式创建定时任务 |
| 扩展 | MCP 协议，可装任意插件 |
| 自愈 | 自动重试 x3、Git 回滚、send_text 网络重试 |
| 中断 | 新消息自动取消 Worker，/cancel 三重取消 |
| 监控 | Web 管理面板 + 进度报告 + 费用追踪 |
| 飞书 | 私聊 + 群聊 @机器人，图片/文件/语音 |
| 消息总线 | 飞书 + Web 面板实时同步，统一消息流 |

## 快速开始

### 前提条件
- Windows 10/11, Python 3.10+, Node.js 18+
- 飞书账号
- VC++ Redistributable（如遇 DLL 加载失败需要安装）

### 安装
`
npm install -g @opencode-ai/cli
git clone https://github.com/yourname/wechat-opencode.git
cd wechat-opencode
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
`

如果网络无法直连 pypi.org，使用国内镜像：
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

### 配置
`
copy config.example.yaml config.yaml
# 编辑 config.yaml，填入 deepseek_api_key、feishu.app_id、feishu.app_secret
`

### 启动
`
python -m wechat_opencode
`

Web 管理面板：http://127.0.0.1:8080

## 指令列表

/help /model /screen /file /focus /open /desktop /min /max /apps
/ppt /plan /tasks /task /status /progress /cancel /undo /sessions
/cost /compact /compact all /cron /new /restart /cleartasks

## 上下文管理
- 自动压缩：1 小时空闲 + 300 条消息触发
- 手动压缩：/compact（监工）/compact all（监工+执行层）

## License
MIT
