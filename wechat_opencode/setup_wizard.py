"""Setup wizard — first-run web configuration for API keys and bot settings."""

import json
import logging
import os
import socket
import webbrowser
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template_string, request

logger = logging.getLogger(__name__)

SETUP_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenCode - 初始化配置</title>
<style>
:root{--bg:#f5f5f7;--card:#fff;--text:#1d1d1f;--sub:#86868b;--accent:#0071e3;--border:rgba(0,0,0,0.08);--radius:12px;--font:-apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.5 var(--font);background:var(--bg);color:var(--text);display:flex;justify-content:center;padding:40px 20px}
.container{width:520px;max-width:100%}
h1{font-size:24px;font-weight:700;margin-bottom:4px;display:flex;align-items:center;gap:10px}
h1 span{font-size:28px}
.desc{color:var(--sub);margin-bottom:24px;font-size:13px}
.card{background:var(--card);border-radius:var(--radius);padding:24px;border:1px solid var(--border);margin-bottom:16px}
.card h3{font-size:14px;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.form-group{margin-bottom:14px}
.form-group:last-child{margin-bottom:0}
label{display:block;font-size:12px;font-weight:600;color:var(--sub);margin-bottom:4px;text-transform:uppercase;letter-spacing:0.05em}
input,select{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px;font-family:var(--font);outline:none;transition:border-color 0.15s}
input:focus,select:focus{border-color:var(--accent)}
input::placeholder{color:#c7c7cc}
.required::after{content:' *';color:#ff3b30}
.hint{font-size:11px;color:var(--sub);margin-top:4px}
.hint a{color:var(--accent)}
.btn{
  width:100%;padding:12px;background:var(--accent);color:#fff;border:none;
  border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;font-family:var(--font);
  transition:background 0.15s;
}
.btn:hover{background:#0077ed}
.btn:disabled{opacity:0.5;cursor:default}
.msg{padding:10px 14px;border-radius:8px;font-size:13px;margin-top:12px;display:none}
.msg.error{background:rgba(255,59,48,0.08);color:#ff3b30;display:block}
.msg.success{background:rgba(52,199,89,0.08);color:#34c759;display:block}
.msg.info{background:rgba(0,113,227,0.08);color:var(--accent);display:block}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin 0.6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.step{display:none}
.step.active{display:block}
.steps{display:flex;gap:8px;margin-bottom:20px}
.step-dot{width:8px;height:8px;border-radius:50%;background:var(--border);transition:background 0.3s}
.step-dot.done{background:var(--accent)}
</style>
</head>
<body>
<div class="container">
<h1><span>🖥️</span> OpenCode</h1>
<div class="desc">首次使用，请完成以下配置。所有信息保存在本地。</div>

<div class="steps">
  <div class="step-dot" id="dot1"></div>
  <div class="step-dot" id="dot2"></div>
  <div class="step-dot" id="dot3"></div>
</div>

<!-- Step 1: API Key -->
<div class="card step active" id="step1">
<h3>🔑 大模型 API Key</h3>
<div class="form-group">
  <label class="required">DeepSeek API Key</label>
  <input type="password" id="apikey" placeholder="sk-..." oninput="checkStep1()">
  <div class="hint">从 <a href="https://platform.deepseek.com/api_keys" target="_blank">platform.deepseek.com</a> 获取</div>
</div>
<button class="btn" id="btn1" disabled onclick="nextStep(1)">下一步</button>
<div class="msg" id="msg1"></div>
</div>

<!-- Step 2: Feishu -->
<div class="card step" id="step2">
<h3>📱 飞书机器人</h3>
<div class="form-group">
  <label class="required">App ID</label>
  <input type="text" id="appid" placeholder="cli_..." oninput="checkStep2()">
</div>
<div class="form-group">
  <label class="required">App Secret</label>
  <input type="password" id="appsecret" placeholder="..." oninput="checkStep2()">
  <div class="hint">在 <a href="https://open.feishu.cn/app" target="_blank">飞书开放平台</a> 创建应用 → 凭证与基础信息</div>
</div>
<button class="btn" id="btn2" disabled onclick="nextStep(2)">下一步</button>
<div class="msg" id="msg2"></div>
</div>

<!-- Step 3: Settings & Save -->
<div class="card step" id="step3">
<h3>⚙️ 其他设置</h3>
<div class="form-group">
  <label>默认模型</label>
  <select id="model">
    <option value="deepseek/deepseek-chat">DeepSeek Chat (Flash - 快速)</option>
    <option value="deepseek/deepseek-v4-pro">DeepSeek V4 Pro (高质量)</option>
  </select>
</div>
<div class="form-group">
  <label>工作目录</label>
  <input type="text" id="workdir" value="" placeholder="C:\Users\...">
  <div class="hint">AI 操作的文件范围。默认是你的用户目录</div>
</div>
<button class="btn" id="btn3" onclick="saveConfig()">
  <span id="btn3txt">保存并启动</span>
</button>
<div class="msg" id="msg3"></div>
</div>

</div>
<script>
function setMsg(n,t,c){let e=document.getElementById('msg'+n);e.textContent=t;e.className='msg '+c}
function checkStep1(){document.getElementById('btn1').disabled=!document.getElementById('apikey').value.trim()}
function checkStep2(){
  let a=document.getElementById('appid').value.trim(),s=document.getElementById('appsecret').value.trim();
  document.getElementById('btn2').disabled=!(a&&s)
}

async function nextStep(n){
  if(n===1){
    let k=document.getElementById('apikey').value.trim();
    document.getElementById('btn1').innerHTML='<span class="spinner"></span>验证中...';
    document.getElementById('btn1').disabled=true;
    setMsg(1,'','');
    try{
      let r=await fetch('/api/validate-key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})});
      let d=await r.json();
      if(d.ok){
        setMsg(1,'✅ API Key 验证成功','success');
        document.getElementById('dot1').classList.add('done');
        switchStep(2);
      }else{
        setMsg(1,'❌ '+d.error,'error');
      }
    }catch(e){setMsg(1,'❌ 网络错误，请重试','error')}
    document.getElementById('btn1').innerHTML='下一步';
    document.getElementById('btn1').disabled=false;
  }else if(n===2){
    let id=document.getElementById('appid').value.trim(),sec=document.getElementById('appsecret').value.trim();
    document.getElementById('btn2').innerHTML='<span class="spinner"></span>验证中...';
    document.getElementById('btn2').disabled=true;
    setMsg(2,'','');
    try{
      let r=await fetch('/api/validate-feishu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({app_id:id,app_secret:sec})});
      let d=await r.json();
      if(d.ok){
        setMsg(2,'✅ 飞书连接成功','success');
        document.getElementById('dot2').classList.add('done');
        switchStep(3);
      }else{
        setMsg(2,'❌ '+d.error,'error');
      }
    }catch(e){setMsg(2,'❌ 网络错误，请重试','error')}
    document.getElementById('btn2').innerHTML='下一步';
    document.getElementById('btn2').disabled=false;
  }
}

function switchStep(n){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));
  document.getElementById('step'+n).classList.add('active');
}

async function saveConfig(){
  let btn=document.getElementById('btn3'),txt=document.getElementById('btn3txt');
  btn.disabled=true;txt.textContent='保存中...';
  let data={
    apikey:document.getElementById('apikey').value.trim(),
    app_id:document.getElementById('appid').value.trim(),
    app_secret:document.getElementById('appsecret').value.trim(),
    model:document.getElementById('model').value,
    workdir:document.getElementById('workdir').value.trim()
  };
  try{
    let r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    let d=await r.json();
    if(d.ok){
      document.getElementById('dot3').classList.add('done');
      setMsg(3,'✅ 配置已保存！服务启动中...','success');
      setTimeout(()=>{window.location.href='http://127.0.0.1:8080'},3000);
    }else{
      setMsg(3,'❌ '+d.error,'error');
    }
  }catch(e){setMsg(3,'❌ 保存失败','error')}
  btn.disabled=false;txt.textContent='保存并启动';
}

// Init
fetch('/api/defaults').then(r=>r.json()).then(d=>{
  if(d.workdir)document.getElementById('workdir').value=d.workdir||'';
  if(d.workdir)document.getElementById('workdir').placeholder=d.workdir||'';
});
</script>
</body>
</html>
"""


def create_app(config_path: str) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(SETUP_HTML)

    @app.route("/api/defaults")
    def api_defaults():
        return jsonify({
            "workdir": str(Path.home()),
        })

    @app.route("/api/validate-key", methods=["POST"])
    def api_validate_key():
        data = request.get_json()
        key = (data.get("key", "")).strip()
        if not key or not key.startswith("sk-"):
            return jsonify({"ok": False, "error": "API Key 格式不正确，应以 sk- 开头"})
        try:
            import requests
            r = requests.get(
                "https://api.deepseek.com/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if r.status_code == 200:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"API 返回 {r.status_code}: {r.text[:100]}"})
        except Exception as e:
            return jsonify({"ok": False, "error": f"连接失败: {e}"})

    @app.route("/api/validate-feishu", methods=["POST"])
    def api_validate_feishu():
        data = request.get_json()
        app_id = data.get("app_id", "").strip()
        app_secret = data.get("app_secret", "").strip()
        if not app_id or not app_secret:
            return jsonify({"ok": False, "error": "App ID 和 App Secret 不能为空"})
        try:
            import requests
            r = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=10,
            )
            if r.status_code == 200 and r.json().get("code") == 0:
                return jsonify({"ok": True})
            return jsonify({"ok": False, "error": f"飞书返回: {r.json().get('msg', r.text[:100])}"})
        except Exception as e:
            return jsonify({"ok": False, "error": f"连接失败: {e}"})

    @app.route("/api/save", methods=["POST"])
    def api_save():
        data = request.get_json()
        apikey = data.get("apikey", "").strip()
        app_id = data.get("app_id", "").strip()
        app_secret = data.get("app_secret", "").strip()
        model = data.get("model", "deepseek/deepseek-chat").strip()
        workdir = data.get("workdir", "").strip() or str(Path.home())

        if not all([apikey, app_id, app_secret]):
            return jsonify({"ok": False, "error": "必填项不能为空"})

        # Save config.yaml
        yaml_config = {
            "bot_type": "feishu",
            "opencode": {
                "project_dir": workdir,
                "serve_port": 4097,
                "worker_serve_port": 4098,
                "serve_host": "127.0.0.1",
                "command_timeout": 300,
            },
            "feishu": {
                "app_id": app_id,
                "app_secret": app_secret,
            },
            "service": {
                "heartbeat_interval": 30,
                "auto_restart": True,
                "log_level": "INFO",
                "log_file": "wechat_opencode.log",
            },
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_config, f, allow_unicode=True, default_flow_style=False)

        # Save opencode.json
        opencode_config = {
            "$schema": "https://opencode.ai/config.json",
            "model": model,
            "mcp": {
                "playwright": {
                    "type": "local", "enabled": True,
                    "command": "npx", "args": ["-y", "@playwright/mcp"],
                },
                "filesystem": {
                    "type": "local", "enabled": True,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", workdir],
                },
            },
        }
        opencode_path = os.path.join(os.path.dirname(config_path), "opencode.json")
        with open(opencode_path, "w", encoding="utf-8") as f:
            json.dump(opencode_config, f, ensure_ascii=False)

        # Set env var for API key
        os.environ["DEEPSEEK_API_KEY"] = apikey

        return jsonify({"ok": True})

    return app


def find_free_port(start: int = 8099) -> int:
    """Find a free TCP port starting from *start*."""
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def run_setup(config_path: str) -> bool:
    """Run the setup wizard. Returns True if config was saved successfully."""
    port = find_free_port(8099)
    app = create_app(config_path)

    logger.info("Setup wizard starting at http://127.0.0.1:%d", port)
    webbrowser.open(f"http://127.0.0.1:{port}")

    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    return True
