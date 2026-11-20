#!/usr/bin/env python3
"""KG Terminal Agent - stdlib only.
Serves a mobile chat UI on port 5000.
- GET / -> chat UI
- POST /api/chat {message} -> Gemini (if GEMINI_API_KEY) else OpenRouter
  (if OPENROUTER_API_KEY) else a no-key reply. Terminal still works.
- POST /api/run {command} -> one allowlisted shell command, 120s timeout.
Run: python3 server.py
"""
import json
import os
import re
import shlex
import subprocess
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "5000"))
ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_OUT = 200 * 1024  # 200 KB

SYSTEM_PROMPT = (
    "You are KG, a terminal agent. Give short, direct answers. "
    "No fluff. If a task needs a terminal command, propose exactly one "
    "safe shell command in a ```bash block so the user can click Run. "
    "Never propose sudo, rm -rf, or piping curl to bash."
)

ALLOWED = {
    "curl", "wget", "grep", "python3", "python", "ls", "pwd", "cat",
    "head", "tail", "wc", "find", "git", "node", "npm", "pip3", "pip",
    "subfinder", "go", "echo", "mkdir", "cp", "mv", "sort", "uniq",
    "jq", "date", "whoami", "uname", "df", "du", "ps", "env",
}

BLOCKED_SUBSTRINGS = [
    "sudo", "rm -rf", "rm -r /", "mkfs", "shutdown", "reboot",
    "chmod 777", "| bash", "| sh", "curl |", "wget |", ">/dev/",
    "dd if=", ":(){",
]

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KG Terminal Agent</title>
<style>
*{box-sizing:border-box}body{font-family:system-ui,Arial,sans-serif;margin:0;background:#0f1115;color:#e8e8e8}
main{max-width:720px;margin:0 auto;padding:14px}
h1{font-size:20px;margin:6px 0 2px}p{color:#aaa;font-size:13px;margin:0 0 12px}
#chat,#out{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:10px;min-height:120px;white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.5}
#out{font-family:monospace;font-size:12px;min-height:140px;max-height:50vh;overflow:auto}
textarea,input{width:100%;background:#171a21;color:#fff;border:1px solid #2a2f3a;border-radius:8px;padding:10px;font-size:15px;margin-top:8px}
button{background:#2f81f7;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-size:15px;margin:8px 6px 0 0;cursor:pointer}
button.run{background:#238636}.quick{background:#21262d;color:#ddd;font-size:13px;padding:7px 10px}
label{display:block;margin-top:14px;font-weight:600}
</style></head><body><main>
<h1>KG Terminal Agent</h1>
<p>Chat with AI, run safe Linux commands. Free in GitHub Codespaces. Not 24/7.</p>
<label>Chat</label><div id="chat">Hi. Ask me something, or run a command below.</div>
<textarea id="msg" rows="2" placeholder="Ask KG... e.g. how do I check if a site is live?"></textarea><br>
<button onclick="sendChat()">Send</button>
<label>Terminal command</label>
<input id="cmd" placeholder="curl -I https://example.com">
<button class="run" onclick="runCmd()">Run command</button>
<div>
<button class="quick" onclick="setCmd('curl -I https://example.com')">curl -I example.com</button>
<button class="quick" onclick="setCmd('ls')">ls</button>
<button class="quick" onclick="setCmd('pwd')">pwd</button>
<button class="quick" onclick="setCmd('echo hello')">echo hello</button>
<button class="quick" onclick="setCmd('python3 scripts/scan_site.py shgora.com')">scan shgora.com</button>
</div>
<label>Output</label><div id="out">Output appears here.</div>
<script>
function setCmd(c){document.getElementById('cmd').value=c;}
function esc(s){return s;}
async function post(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
async function sendChat(){
  const m=document.getElementById('msg').value.trim(); if(!m) return;
  const chat=document.getElementById('chat');
  chat.textContent+='\n\nYou: '+m+'\nKG: ...';
  try{
    const d=await post('/api/chat',{message:m});
    chat.textContent+='\n'+(d.reply||d.error||'No reply');
    // Offer Run buttons for ```bash blocks
    const blocks=[...(d.reply||'').matchAll(/```bash\n([\s\S]*?)```/g)];
    blocks.forEach(b=>{
      const btn=document.createElement('button'); btn.className='run';
      btn.textContent='Run: '+b[1].trim().slice(0,60);
      btn.onclick=()=>{setCmd(b[1].trim()); runCmd();};
      chat.appendChild(document.createElement('br')); chat.appendChild(btn);
    });
  }catch(e){chat.textContent+='\nError: '+e;}
  document.getElementById('msg').value='';
}
async function runCmd(){
  const c=document.getElementById('cmd').value.trim(); if(!c) return;
  const out=document.getElementById('out'); out.textContent='Running: '+c+'\n...';
  try{
    const d=await post('/api/run',{command:c});
    if(d.ok){ out.textContent='exit '+d.exit_code+'\n'+(d.stdout||'')+(d.stderr?'\nSTDERR:\n'+d.stderr:''); }
    else { out.textContent='Blocked / error: '+(d.error||'unknown'); }
  }catch(e){out.textContent='Error: '+e;}
}
</script></main></body></html>
"""


def _cap(text):
    if len(text.encode("utf-8", "ignore")) > MAX_OUT:
        return text.encode("utf-8", "ignore")[:MAX_OUT].decode("utf-8", "ignore") + "\n[output truncated at 200KB]"
    return text


def _post_json(url, payload, headers):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _gemini_reply(message):
    key = os.environ.get("GEMINI_API_KEY", "")
    prompt = SYSTEM_PROMPT + "\n\nUser: " + message
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    last_err = ""
    for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            data = _post_json(url, payload, headers)
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return {"ok": True, "reply": text, "model": model}
        except Exception as e:
            last_err = str(e)
    return {"ok": False, "reply": "", "error": f"Gemini failed: {last_err}"}


def _openrouter_reply(message):
    key = os.environ.get("OPENROUTER_API_KEY", "")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://github.com/gamme1/kg-terminal-agent",
        "X-Title": "KG Terminal Agent",
    }
    payload = {
        "model": "openrouter/auto",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    }
    try:
        data = _post_json("https://openrouter.ai/api/v1/chat/completions", payload, headers)
        return {"ok": True, "reply": data["choices"][0]["message"]["content"], "model": "openrouter/auto"}
    except Exception:
        payload["model"] = "google/gemini-2.0-flash-001:free"
        try:
            data = _post_json("https://openrouter.ai/api/v1/chat/completions", payload, headers)
            return {"ok": True, "reply": data["choices"][0]["message"]["content"], "model": "google/gemini-2.0-flash-001:free"}
        except Exception as e:
            return {"ok": False, "reply": "", "error": f"OpenRouter failed: {e}"}


def _blocked_reason(command):
    low = command.lower()
    for bad in BLOCKED_SUBSTRINGS:
        if bad in low:
            return f"blocked: contains '{bad}'"
    # token-level blocks: su / ssh / nc / ncat as a command word
    tokens = re.split(r"[\s;|&]+", low)
    for bad in ("sudo", "su", "ssh", "nc", "ncat", "mkfs", "shutdown", "reboot"):
        if bad in tokens:
            return f"blocked: '{bad}' is not allowed"
    if not command.strip():
        return "blocked: empty command"
    try:
        first = shlex.split(command)[0]
    except Exception:
        return "blocked: could not parse command"
    if first not in ALLOWED:
        return f"blocked: '{first}' is not in the allowlist"
    return None


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._html()
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode() or "{}")
        except Exception as e:
            return self._json({"ok": False, "error": f"bad JSON: {e}"}, 400)

        if self.path == "/api/chat":
            message = str(data.get("message", "")).strip()
            if not message:
                return self._json({"ok": False, "error": "empty message"}, 400)
            if os.environ.get("GEMINI_API_KEY"):
                return self._json(_gemini_reply(message))
            if os.environ.get("OPENROUTER_API_KEY"):
                return self._json(_openrouter_reply(message))
            return self._json({
                "ok": True,
                "model": "none",
                "reply": (
                    "No API key set yet, so I am running without AI chat.\n"
                    "Set one in Codespaces secrets, or in the terminal:\n"
                    "export GEMINI_API_KEY=your-key\n"
                    "then restart with: python3 server.py\n"
                    "Never paste a key in this chat.\n\n"
                    "Terminal commands still work below. Try:\n"
                    "curl -I https://example.com"
                ),
            })

        if self.path == "/api/run":
            command = str(data.get("command", "")).strip()
            reason = _blocked_reason(command)
            if reason:
                return self._json({"ok": False, "error": reason})
            try:
                args = shlex.split(command)
                proc = subprocess.run(
                    args, cwd=ROOT, capture_output=True, text=True,
                    timeout=120, env=os.environ.copy(),
                )
                return self._json({
                    "ok": True,
                    "stdout": _cap(proc.stdout or ""),
                    "stderr": _cap(proc.stderr or ""),
                    "exit_code": proc.returncode,
                })
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "error": "timeout after 120s"})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})

        return self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        # Keep logs quiet but visible.
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"KG Terminal Agent on http://localhost:{PORT}  (root={ROOT})", flush=True)
    print("Set GEMINI_API_KEY or OPENROUTER_API_KEY to enable AI chat.", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
