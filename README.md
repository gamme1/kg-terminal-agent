# KG Terminal Agent

Chat with AI on a website, run safe Linux terminal commands. Phone only, no PC needed.

Two free ways to run it. Option 1 is for full terminal power. Option 2 is free forever, for chat + small commands.

## Option 1 — GitHub Codespaces (full terminal power)

1. Open **github.com/gamme1/kg-terminal-agent** in your browser
2. Tap **Code** > **Create codespace on main**
3. Wait for the build to finish
4. Set your AI key (pick one):
   - Codespaces secrets, or in the terminal:
     ```
     export GEMINI_API_KEY=your-key
     ```
   - Never paste a key in the chat.
5. Run:
   ```
   python3 server.py
   ```
   Or: `bash start.sh`
6. Click the **port 5000** popup > **Open in Browser**. Chat on the website.

### Codespaces limits (honest)

- Free: 120 core-hours/month, about 60 hours on a 2-core machine
- Stops after 30 minutes idle
- Max 12 hours per session
- Not 24/7. When it stops, start a new codespace.

## Option 2 — Render free forever (chat + small commands)

Same as SiraLink, you already use Render.

1. Push this repo to GitHub
2. Render dashboard > **New Web Service** > pick the repo
3. Plan: **Free** (`render.yaml` in this repo sets it up: name `kg-terminal-agent`, start `python3 server.py`)
4. Set `GEMINI_API_KEY` in Environment (or `OPENROUTER_API_KEY`)
5. Deploy, open the `onrender.com` URL and chat.

### Render limits (honest)

- Free forever, 750 hours/month
- Sleeps after ~15 min idle, first load is slow (cold start ~50s)
- No root/sudo, cannot install subfinder/apt
- `curl`, `python`, `grep` work
- Files/storage reset on redeploy
- For chat + small commands only. NOT for the big 739MB download scan — use Codespaces (Option 1) for that.

## Quick commands to try

```
curl -I https://example.com
ls
pwd
python3 scripts/scan_site.py shgora.com
```

Only scan a site you own. `scan_site.py` is GET/HEAD only, no login guessing.

## Files

- `server.py` — chat website + terminal runner, Python stdlib only, listens on `$PORT` (default 5000), binds 0.0.0.0
- `render.yaml` — Render free web service config
- `scripts/scan_site.py` — safe site check (subfinder if installed, live check, JS/API grep, mp4 test)
- `scripts/install_tools.sh` — installs subfinder in Codespaces, skips safely if it fails
- `.devcontainer/devcontainer.json` — Codespaces setup
- `start.sh` — `python3 server.py`
- `requirements.txt` — empty, stdlib only, nothing to install
