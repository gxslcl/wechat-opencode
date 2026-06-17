"""Web UI — local chat interface for the desktop."""

import json
import logging
import os
import threading
import time
import webbrowser
from typing import Any, Optional

from flask import Flask, jsonify, render_template_string, request

logger = logging.getLogger(__name__)

# Suppress Flask/Werkzeug access logs
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Globals set by core.py after initialization
_session: Any = None
_supervisor_id: str = ""
_get_worker_status: Any = lambda: {}
_get_tasks: Any = lambda: []
_get_costs: Any = lambda: ""
_get_model: Any = lambda: ""
_exec_queue: Any = None
_bus: Any = None

app = Flask(__name__)
_state = {"local_sent": set(), "started_at": time.time(), "sent_count": 0}
SKIP_MARKERS = ["你是监工", "你是执行层", "只回复'明白了'"]


def _clean_message(text: str, role: str) -> str:
    """Strip injected context from messages before display."""
    if role == "user" and "用户指令:" in text:
        idx = text.rfind("用户指令:")
        if idx >= 0:
            return text[idx + 5:].strip()
    if text.startswith("[上下文]"):
        for marker in ["用户指令:", "工作目录:", "最近任务:"]:
            idx = text.find(marker)
            if idx > 0:
                return text[idx:].strip()
    return text


CHAT_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCode Desktop</title>
<style>
:root{
  --bg:#f5f5f7;--sidebar-bg:rgba(245,245,247,0.72);--card-bg:#ffffff;
  --text:#1d1d1f;--text-secondary:#86868b;--accent:#0071e3;--accent-hover:#0077ed;
  --bubble-user:#0071e3;--bubble-bot:#ffffff;--border:rgba(0,0,0,0.06);
  --shadow:0 1px 3px rgba(0,0,0,0.04),0 1px 2px rgba(0,0,0,0.06);
  --radius:14px;--font:-apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif;
}
[data-theme="dark"]{
  --bg:#1c1c1e;--sidebar-bg:rgba(28,28,30,0.8);--card-bg:#2c2c2e;
  --text:#f5f5f7;--text-secondary:#98989d;--accent:#0a84ff;--accent-hover:#409cff;
  --bubble-user:#0a84ff;--bubble-bot:#2c2c2e;--border:rgba(255,255,255,0.08);
  --shadow:0 1px 3px rgba(0,0,0,0.2);
}
[data-theme="dark"] .quick-btn.danger{color:#ff453a}
[data-theme="dark"] .quick-btn.danger:hover{background:rgba(255,69,58,0.1)}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.5 var(--font);background:var(--bg);color:var(--text);display:flex;height:100vh;-webkit-font-smoothing:antialiased}
.sidebar{width:260px;background:var(--sidebar-bg);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-right:1px solid var(--border);padding:20px 16px;overflow-y:auto;flex-shrink:0;display:flex;flex-direction:column;gap:16px}
.sidebar .logo{font-size:13px;font-weight:600;letter-spacing:-0.01em;display:flex;align-items:center;gap:8px}
.sidebar .logo span{font-size:18px}
.sidebar h4{font-size:11px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px}
.status-card{background:var(--card-bg);border-radius:12px;padding:14px;box-shadow:var(--shadow);border:1px solid var(--border)}
.status-card .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-card .dot.idle{background:#34c759}
.status-card .dot.running{background:var(--accent);animation:pulse 1.5s infinite}
.status-card .label{font-size:11px;color:var(--text-secondary)}
.status-card .task-name{font-size:13px;font-weight:500;margin-top:4px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.task-item{padding:6px 10px;font-size:12px;border-radius:8px;color:var(--text-secondary)}
.meta-item{font-size:11px;color:var(--text-secondary);padding:4px 0}
.quick-btn{display:flex;align-items:center;gap:8px;width:100%;padding:8px 12px;border:none;background:transparent;color:var(--text);font-size:13px;border-radius:8px;cursor:pointer;transition:background 0.15s;font-family:var(--font)}
.quick-btn:hover{background:var(--card-bg)}
.quick-btn .icon{font-size:16px;width:20px;text-align:center}
.quick-btn.danger{color:#ff3b30}
.quick-btn.danger:hover{background:rgba(255,59,48,0.08)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.chat-header{padding:12px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--sidebar-bg);backdrop-filter:blur(24px)}
.chat-header .title{font-size:13px;font-weight:600}
.chat{flex:1;overflow-y:auto;padding:20px 40px;display:flex;flex-direction:column;gap:6px}
.msg{display:flex;max-width:80%;animation:fadeIn 0.3s ease}
.msg.user,.msg.phone{align-self:flex-end;flex-direction:row-reverse}
.msg.bot{align-self:flex-start}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.bubble{padding:10px 16px;border-radius:var(--radius);font-size:14px;line-height:1.5;word-break:break-word;position:relative;box-shadow:var(--shadow)}
.msg.user .bubble{background:var(--bubble-user);color:#fff;border-bottom-right-radius:4px}
.msg.bot .bubble,.msg.phone .bubble{background:var(--bubble-bot);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg.phone .bubble{border:1px solid rgba(0,113,227,0.15)}
.bubble .label{font-size:10px;margin-bottom:4px;opacity:0.5;font-weight:500}
.msg.user .bubble .label{color:rgba(255,255,255,0.7)}
.bubble .time{font-size:10px;opacity:0.4;margin-top:4px;text-align:right}
.msg .copy-btn{position:absolute;top:4px;right:4px;padding:2px 6px;background:rgba(0,0,0,0.05);border:none;border-radius:4px;cursor:pointer;font-size:10px;opacity:0;transition:opacity 0.15s}
.msg:hover .copy-btn{opacity:1}
.scroll-bottom{position:fixed;bottom:80px;right:40px;width:36px;height:36px;background:var(--card-bg);border:1px solid var(--border);border-radius:50%;display:none;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow);font-size:18px;z-index:10}
.input-bar{background:var(--sidebar-bg);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-top:1px solid var(--border);padding:12px 20px;display:flex;gap:10px;align-items:flex-end;position:relative}
.input-bar textarea{flex:1;padding:10px 16px;background:var(--card-bg);border:1px solid var(--border);color:var(--text);border-radius:20px;outline:none;font-size:14px;font-family:var(--font);box-shadow:var(--shadow);transition:border-color 0.15s;resize:none;min-height:42px;max-height:120px;line-height:1.4}
.input-bar textarea:focus{border-color:var(--accent)}
.input-bar button{padding:10px 20px;background:var(--accent);border:none;color:#fff;border-radius:20px;cursor:pointer;font-size:14px;font-weight:500;font-family:var(--font);transition:background 0.15s;white-space:nowrap}
.input-bar button:hover{background:var(--accent-hover)}
.input-bar button:active{transform:scale(0.97)}
.input-bar button:disabled{opacity:0.5}
.loading{text-align:center;padding:60px 20px;color:var(--text-secondary)}
.typing{cursor:default}
.typing::after{content:'|';animation:blink 1s infinite}
@keyframes blink{0%,50%{opacity:1}51%,100%{opacity:0}}
.toast{position:fixed;top:16px;left:50%;transform:translateX(-50%);background:#1d1d1f;color:#fff;padding:8px 20px;border-radius:8px;font-size:13px;z-index:100;opacity:0;transition:opacity 0.3s}
.toast.show{opacity:1}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:50;display:none;align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal-box{background:var(--card-bg);border-radius:14px;box-shadow:0 16px 48px rgba(0,0,0,0.2);width:560px;max-width:90vw;max-height:80vh;overflow:hidden}
.modal-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:14px;font-weight:600}
.modal-body{padding:14px 18px}
[data-theme="dark"] .modal-overlay{background:rgba(0,0,0,0.6)}
.bubble pre{background:rgba(0,0,0,0.06);border-radius:8px;padding:12px;overflow-x:auto;margin:8px 0;font-size:13px}
.bubble code{font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px}
.bubble p{margin:4px 0}
.bubble ul,.bubble ol{padding-left:20px;margin:4px 0}
.bubble blockquote{border-left:3px solid var(--accent);padding-left:12px;margin:8px 0;opacity:0.8}
.bubble a{color:var(--accent)}
[data-theme="dark"] .bubble pre{background:rgba(255,255,255,0.06)}
.cmd-panel{position:absolute;bottom:100%;left:20px;right:20px;background:var(--card-bg);border:1px solid var(--border);border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.12);max-height:260px;overflow-y:auto;display:none;z-index:20}
.cmd-panel.show{display:block}
.cmd-item{padding:8px 14px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;transition:background 0.1s}
.cmd-item:hover,.cmd-item.active{background:var(--accent);color:#fff}
.cmd-item .desc{font-size:11px;opacity:0.6}
</style>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
</head>
<body>
<div class="sidebar">
  <div class="logo"><span>🖥️</span> OpenCode</div>
  <div style="display:flex;gap:8px">
    <button class="quick-btn" id="theme-btn" onclick="toggleTheme()" style="font-size:12px"><span class="icon">🌙</span>暗色</button>
  </div>
  <div class="sidebar-section"><h4>状态</h4><div class="status-card" id="worker-status"><div class="dot idle" style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:#34c759"></div><span class="label">就绪</span></div></div>
  <div class="sidebar-section"><h4>模型</h4><div class="meta-item" id="model-info">--</div></div>
  <div class="sidebar-section"><h4>任务</h4><div id="task-list"></div></div>
  <div class="sidebar-section">
    <h4>操作</h4>
    <button class="quick-btn" onclick="sendCmd('/screen')"><span class="icon">📸</span>截图</button>
    <button class="quick-btn" onclick="sendCmd('/cost')"><span class="icon">💰</span>费用</button>
    <button class="quick-btn" onclick="sendCmd('/tasks')"><span class="icon">📋</span>任务</button>
    <button class="quick-btn" onclick="sendCmd('/model')"><span class="icon">🤖</span>模型</button>
    <button class="quick-btn" onclick="sendCmd('/new')"><span class="icon">✨</span>新任务</button>
    <button class="quick-btn" onclick="exportChat()"><span class="icon">📥</span>导出对话</button>
    <button class="quick-btn" onclick="toggleWorkerLog()"><span class="icon">📋</span>Worker 日志</button>
    <button class="quick-btn danger" onclick="clearChat()"><span class="icon">🗑️</span>清空记录</button>
  </div>
</div>
<div class="main">
  <div class="chat-header"><div class="title">💬 对话</div><span style="font-size:11px;color:var(--text-secondary)" id="conn-status">● 连接中</span></div>
  <div class="chat" id="chat"><div class="loading">连接中...</div></div>
  <div class="scroll-bottom" id="scroll-btn" onclick="scrollToBottom()" title="回到底部">↓</div>
  <div class="input-bar">
    <div class="cmd-panel" id="cmd-panel"></div>
    <textarea id="input" rows="1" placeholder="输入消息，Enter 发送，输入 / 查看指令..."
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
    <button id="send-btn" onclick="send()">发送</button>
  </div>
</div>
<div class="toast" id="toast"></div>
<div class="modal-overlay" id="log-modal" onclick="if(event.target===this)toggleWorkerLog()">
  <div class="modal-box">
    <div class="modal-header"><span>📋 Worker 日志</span><button onclick="toggleWorkerLog()" style="background:none;border:none;font-size:18px;cursor:pointer;color:var(--text-secondary)">✕</button></div>
    <div id="worker-log" class="modal-body" style="font-size:12px;line-height:1.5;max-height:60vh;overflow-y:auto"></div>
  </div>
</div>
<script>
const STORAGE_KEY='opencode_chat_msgs',MAX_STORED=200;
let chatEl=document.getElementById('chat'),sending=false,connected=false;
let seenMsgSet=new Set();

// === LocalStorage ===
function loadMsgs(){try{return JSON.parse(localStorage.getItem(STORAGE_KEY))||[]}catch(e){return[]}}
function saveMsgs(msgs){try{if(msgs.length>MAX_STORED)msgs=msgs.slice(-MAX_STORED);localStorage.setItem(STORAGE_KEY,JSON.stringify(msgs))}catch(e){}}

// === Theme ===
function initTheme(){let t=localStorage.getItem('opencode_theme')||'light';document.documentElement.setAttribute('data-theme',t);updateThemeBtn(t)}
function toggleTheme(){let c=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';document.documentElement.setAttribute('data-theme',c);localStorage.setItem('opencode_theme',c);updateThemeBtn(c)}
function updateThemeBtn(t){document.getElementById('theme-btn').innerHTML=t==='dark'?'<span class="icon">☀️</span>亮色':'<span class="icon">🌙</span>暗色'}

// === Markdown ===
function renderMarkdown(text){if(!text)return'';try{return marked.parse(text,{breaks:true,gfm:true})}catch(e){return text.replace(/\n/g,'<br>')}}

// === Render message ===
function addMsgEl(role,text,label,ts,animate){
  let d=document.createElement('div');d.className='msg '+role;
  let b=document.createElement('div');b.className='bubble';
  let h='';
  if(label)h+='<div class="label">'+label+'</div>';
  h+='<div class="content"></div>';
  if(ts){let t=new Date(ts);h+='<div class="time">'+t.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})+'</div>'}
  h+='<button class="copy-btn" onclick="copyMsg(this)" title="复制">📋</button>';
  b.innerHTML=h;d.appendChild(b);chatEl.appendChild(d);
  let content=b.querySelector('.content');
  if(animate&&role==='bot'&&text.length>30){
    typewriter(content,text);
  }else if(role==='bot'){
    content.innerHTML=renderMarkdown(text);
  }else{
    content.textContent=text;
  }
}
function typewriter(el,text,speed=6){
  let i=0;el.classList.add('typing');
  function tick(){if(i<text.length){el.textContent=text.slice(0,i+1);i++;setTimeout(tick,speed)}else{el.classList.remove('typing')}}
  tick();
}
function copyMsg(btn){let t=btn.parentElement.querySelector('.content').textContent;navigator.clipboard.writeText(t).then(()=>{btn.textContent='✅';setTimeout(()=>btn.textContent='📋',1500)})}

// === Persist ===
function persistMsg(role,text,label,ts){
  let msgs=loadMsgs();msgs.push({role,text,label,ts:ts||Date.now()});saveMsgs(msgs);
}
function restoreChat(){
  let msgs=loadMsgs();if(!msgs.length)return;
  document.querySelector('.loading')?.remove();
  msgs.forEach(m=>{addMsgEl(m.role,m.text,m.label,m.ts,false);seenMsgSet.add(m.role+'|'+m.text)});
  scrollToBottom();
}

// === Poll ===
async function poll(){
  try{
    let r=await fetch('/api/messages');let d=await r.json();
    if(!connected){connected=true;document.querySelector('.loading')?.remove();document.getElementById('conn-status').textContent='● 已连接'}
    let msgs=loadMsgs(),saved=false;
    for(let m of d.messages||[]){
      let key=m.role+'|'+m.text;if(seenMsgSet.has(key))continue;seenMsgSet.add(key);
      let role=m.role==='user'?'phone':'bot',label=m.role==='user'?'📱 手机':'🤖 监工',ts=m.timestamp*1000;
      addMsgEl(role,m.text,label,ts,role==='bot'&&m.text.length>30);persistMsg(role,m.text,label,ts);saved=true;
    }
    if(saved)scrollToBottom();
    updateSidebar(d);
  }catch(e){
    connected=false;document.getElementById('conn-status').innerHTML='<span style="color:#ff3b30">● 断开</span>';
    if(!chatEl.querySelector('.loading')&&!chatEl.children.length){let d=document.createElement('div');d.className='loading';d.textContent='连接失败，正在重试...';chatEl.appendChild(d)}
  }
}
function updateSidebar(d){
  let ws=d.worker_status||'空闲',sc=document.getElementById('worker-status'),isRunning=ws.includes('⏳');
  sc.innerHTML='<div class="dot '+(isRunning?'running':'idle')+'" style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;'+(isRunning?'background:var(--accent);animation:pulse 1.5s infinite':'background:#34c759')+'"></div><span class="label">'+(isRunning?'执行中':'就绪')+'</span>'+(isRunning?'<div class="task-name">'+ws.replace('⏳ ','')+'</div>':'');
  if(d.model)document.getElementById('model-info').textContent=d.model;
  // Task list with step count
  let tasks=d.tasks||[];
  document.getElementById('task-list').innerHTML=tasks.length?tasks.map(t=>{
    let icon=t.includes('✅')?'✅':t.includes('❌')?'❌':'⬜';
    return '<div class="task-item" style="display:flex;gap:6px;align-items:flex-start"><span>'+icon+'</span><span>'+t.replace(/^[✅❌⬜]\s*/,'')+'</span></div>';
  }).join(''):'<div class="task-item" style="color:var(--text-secondary)">暂无任务</div>';
}

// === Send ===
function send(){
  if(sending)return;let v=document.getElementById('input').value.trim();if(!v)return;
  sending=true;document.getElementById('send-btn').disabled=true;
  addMsgEl('user',v,'📱 你');persistMsg('user',v,'📱 你');seenMsgSet.add('user|'+v);
  document.getElementById('input').value='';document.getElementById('input').style.height='42px';
  fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:v})})
  .catch(e=>{showToast('❌ 发送失败')})
  .finally(()=>{sending=false;document.getElementById('send-btn').disabled=false});
  scrollToBottom();
}
function sendCmd(c){document.getElementById('input').value=c;send();}

// === Command panel ===
const CMDS=[{cmd:'/screen',desc:'截取电脑桌面'},{cmd:'/file',desc:'搜索并发送文件'},{cmd:'/focus',desc:'切换窗口到前台'},{cmd:'/open',desc:'打开应用或文件'},{cmd:'/desktop',desc:'显示桌面'},{cmd:'/min',desc:'最小化窗口'},{cmd:'/max',desc:'最大化窗口'},{cmd:'/apps',desc:'运行中应用'},{cmd:'/model',desc:'切换模型'},{cmd:'/ppt',desc:'生成PPT'},{cmd:'/plan',desc:'规划执行'},{cmd:'/status',desc:'查看状态'},{cmd:'/progress',desc:'进度报告'},{cmd:'/tasks',desc:'任务列表'},{cmd:'/sessions',desc:'会话列表'},{cmd:'/cost',desc:'费用统计'},{cmd:'/undo',desc:'撤销操作'},{cmd:'/cancel',desc:'取消任务'},{cmd:'/new',desc:'新会话'},{cmd:'/help',desc:'全部指令'},{cmd:'/stop',desc:'关闭服务'}];
let cmdIdx=-1;
function showCmdPanel(v){
  let p=document.getElementById('cmd-panel');if(!v.startsWith('/')){p.classList.remove('show');cmdIdx=-1;return}
  let q=v.slice(1).toLowerCase(),matches=CMDS.filter(c=>c.cmd.slice(1).startsWith(q)||c.desc.includes(q));
  if(!matches.length){p.classList.remove('show');cmdIdx=-1;return}
  p.innerHTML=matches.map((c,i)=>'<div class="cmd-item'+(i===cmdIdx?' active':'')+'" data-cmd="'+c.cmd+'"><span>'+c.cmd+'</span><span class="desc">'+c.desc+'</span></div>').join('');
  p.classList.add('show');
  p.querySelectorAll('.cmd-item').forEach(el=>el.onclick=function(){document.getElementById('input').value=this.dataset.cmd+' ';p.classList.remove('show');cmdIdx=-1;document.getElementById('input').focus()});
}

// === Actions ===
function clearChat(){if(!confirm('确定要清空所有聊天记录吗？'))return;localStorage.removeItem(STORAGE_KEY);chatEl.innerHTML='';seenMsgSet=new Set();showToast('✅ 已清空')}
function exportChat(){
  let msgs=loadMsgs();if(!msgs.length){showToast('没有可导出的消息');return}
  let md='# OpenCode 对话\n\n> '+new Date().toLocaleString()+'\n\n---\n\n';
  msgs.forEach(m=>{md+='**'+(m.role==='user'?'📱 你':'🤖 监工')+'**\n\n'+m.text+'\n\n---\n\n'});
  let b=new Blob([md],{type:'text/markdown'});let a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='opencode-chat.md';a.click();showToast('✅ 已导出')
}
function toggleWorkerLog(){document.getElementById('log-modal').classList.toggle('show')}
function showToast(msg){let t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2000)}
function scrollToBottom(){chatEl.scrollTop=chatEl.scrollHeight}

// === Scroll ===
chatEl.addEventListener('scroll',()=>{let b=document.getElementById('scroll-btn');b.style.display=chatEl.scrollHeight-chatEl.scrollTop-chatEl.clientHeight>200?'flex':'none'});

// === Textarea + keyboard ===
let inputEl=document.getElementById('input');
inputEl.addEventListener('input',function(){this.style.height='42px';this.style.height=Math.min(this.scrollHeight,120)+'px';showCmdPanel(this.value)});
inputEl.addEventListener('keydown',function(e){
  let p=document.getElementById('cmd-panel');if(!p.classList.contains('show'))return;
  let items=p.querySelectorAll('.cmd-item');
  if(e.key==='ArrowDown'){e.preventDefault();cmdIdx=Math.min(cmdIdx+1,items.length-1);showCmdPanel(this.value)}
  else if(e.key==='ArrowUp'){e.preventDefault();cmdIdx=Math.max(cmdIdx-1,0);showCmdPanel(this.value)}
  else if(e.key==='Tab'||e.key==='Enter'){if(cmdIdx>=0&&items[cmdIdx]){e.preventDefault();this.value=items[cmdIdx].dataset.cmd+' ';p.classList.remove('show');cmdIdx=-1}}
  else if(e.key==='Escape'){p.classList.remove('show');cmdIdx=-1}
});

// === Worker log poll ===
async function pollWorkerLog(){
  if(!document.getElementById('log-modal').classList.contains('show'))return;
  try{let r=await fetch('/api/worker-log');let d=await r.json();let wl=document.getElementById('worker-log');wl.innerHTML=(d.lines||[]).map(l=>'<div style="padding:2px 0;border-bottom:1px solid var(--border)">'+l.replace(/</g,'&lt;')+'</div>').join('')||'<div style="color:var(--text-secondary)">暂无日志</div>'}catch(e){}
}

// === Init ===
initTheme();restoreChat();setInterval(poll,1500);setInterval(pollWorkerLog,2000);poll();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(CHAT_HTML)


@app.route("/api/messages")
def api_messages():
    messages = []
    worker_status = "空闲"

    if _bus is not None:
        try:
            raw = _bus.get_messages(since_id="", limit=50)
        except Exception:
            raw = []

        for msg in raw:
            text = msg.get("text", "").strip()
            bus_role = msg.get("role", "")
            source = msg.get("source", "")

            if not text or any(m in text for m in SKIP_MARKERS):
                continue

            if bus_role == "user" and text in _state.get("local_sent", set()):
                continue

            label = "📱 手机" if source == "feishu" else ("📱 你" if bus_role == "user" else "🤖 监工")
            messages.append({
                "id": msg.get("id", str(time.time())),
                "text": text,
                "role": "bot" if bus_role == "assistant" else "user",
                "label": label,
                "timestamp": msg.get("timestamp", time.time()),
            })

    try:
        ws = _get_worker_status()
        if ws.get("status") == "running":
            elapsed = int(time.time() - ws.get("started_at", time.time()))
            worker_status = f'⏳ {ws.get("task","执行中")[:30]} ({elapsed}s)'
    except Exception:
        pass

    return jsonify({
        "messages": messages,
        "worker_status": worker_status,
        "tasks": _get_tasks()[:5],
        "costs": _get_costs(),
        "model": _get_model(),
    })


@app.route("/api/worker-log")
def api_worker_log():
    import os as _os
    log_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "wechat_opencode.log")
    lines = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        for line in reversed(all_lines[-200:]):
            if any(kw in line for kw in ("worker", "Worker", "进度", "结果",
                                           "TASK", "progress", "result", "Result",
                                           "执行", "error", "Error")):
                if "]" in line:
                    msg = line.split("]", 3)[-1].strip()
                else:
                    msg = line.strip()
                if len(msg) > 120:
                    msg = msg[:117] + "..."
                lines.append(msg)
            if len(lines) >= 15:
                break
        lines.reverse()
    except Exception:
        pass
    return jsonify({"lines": lines})


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"ok": False}), 400

    if "local_sent" not in _state:
        _state["local_sent"] = set()
    _state["local_sent"].add(text)
    if len(_state["local_sent"]) > 200:
        _state["local_sent"] = set(list(_state["local_sent"])[-100:])

    # Publish to message bus — core's subscriber will pick it up
    if _bus is not None:
        _bus.publish("incoming", {
            "channel": "incoming",
            "text": text,
            "role": "user",
            "source": "web",
            "sender": "web",
        })
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    return jsonify({
        "worker": _get_worker_status(),
        "tasks": _get_tasks()[:5],
        "costs": _get_costs(),
        "model": _get_model(),
    })


def start_server(
    session: Any,
    supervisor_id: str,
    worker_status_fn: Any,
    tasks_fn: Any,
    costs_fn: Any,
    model_fn: Any,
    queue: Any,
    bus: Any = None,
    port: int = 8080,
):
    global _session, _supervisor_id, _get_worker_status, _get_tasks, _get_costs, _get_model, _exec_queue, _bus
    _session = session
    _supervisor_id = supervisor_id
    _get_worker_status = worker_status_fn
    _get_tasks = tasks_fn
    _get_costs = costs_fn
    _get_model = model_fn
    _exec_queue = queue
    _bus = bus

    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    time.sleep(1)
    webbrowser.open(f"http://127.0.0.1:{port}")
    logger.info("Web UI started at http://127.0.0.1:%d", port)
