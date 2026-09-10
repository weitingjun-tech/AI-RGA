# /run — Launch the RAG Knowledge Base System

This skill covers starting **both** backend (FastAPI, port 8000) and frontend (Vite, port 5173), verifying they are healthy, and optionally running an end-to-end smoke test.

## Prerequisites

| Requirement | How to check |
|---|---|
| MySQL 8.0+ | `mysql -u root -p` or `curl -s http://localhost:3306` |
| Ollama running | `curl -s http://localhost:11434/api/tags` (should return model list) |
| Node.js 18+ (for frontend dev server) | `node --version` |
| Python 3.11+ with venv | `./backend/venv/Scripts/python.exe --version` |

All four must be satisfied before starting. If any are missing, report which one and stop.

## Startup

### 1. Start the Backend (detached, survives session close)

The backend is a FastAPI app at `app/main.py`, using the project venv for dependencies.

```bash
cd d:/mydo/backend
./venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Important:** a plain background shell (`nohup ... &`) and the `Process::Start(file, args)` overload both die when the Claude session ends. To launch a process that **survives session close**, use `ProcessStartInfo` with `UseShellExecute = $true`, and set `WorkingDirectory` *before* calling `Start()`:

```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'd:\mydo\backend\venv\Scripts\python.exe'
$psi.Arguments = '-m uvicorn app.main:app --host 0.0.0.0 --port 8000'
$psi.WorkingDirectory = 'd:\mydo\backend'   # MUST be set before Start()
$psi.UseShellExecute = $true                 # detaches from the parent -> survives
$psi.WindowStyle = 'Hidden'
$p = [System.Diagnostics.Process]::Start($psi)
Write-Host ('Backend started, PID=' + $p.Id)
```

Do NOT use `--reload` here — it spawns a supervisor + worker pair, and killing one leaves the other holding the port (a recurring source of "port 8000 busy" confusion). Only add `--reload` during active development, launched in a normal terminal window.

To restart cleanly, first free the port:

```bash
netstat -ano | grep ":8000.*LISTENING"     # find the PID
taskkill //PID <pid> //T //F                # /T kills the child worker too
```

Wait ~15 seconds for embedding model initialization, then verify:

```bash
curl -s http://localhost:8000/docs -o /dev/null -w "%{http_code}\n"
```

Expected: `200`. If you see anything else, read `backend_8000.log` (if redirected) or check the console output for errors.

If the port is already occupied, find and kill the old process first:

```bash
# Find who owns port 8000
netstat -ano | grep ":8000.*LISTENING"
# Kill all python processes tied to the old backend
taskkill //PID <PID> //T //F
```

Then restart.

### 2. Start the Frontend (Vite dev server)

In a second terminal/window:

```bash
cd d:/mydo/frontend
npx vite --host 0.0.0.0 --port 5173
```

Or with npm:

```bash
npm run dev
```

The Vite dev server serves from source modules directly, so edits to `.tsx/.ts` files (like `KbManage.tsx`) take effect instantly via HMR — no rebuild needed.

Wait ~5 seconds, then verify:

```bash
curl -s http://localhost:5173/ | grep "vite/client"
```

You should see `vite/client` or `react-refresh` in the HTML response. HTTP code should be `200`.

### 3. Verify Both Are Running

```bash
curl -s -o /dev/null -w "backend: %{http_code}\n" http://localhost:8000/docs
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173/
```

Both should return `200`.

## End-to-End Smoke Test (optional but recommended)

After both services respond, verify the upload pipeline works with a small epub:

```bash
cd d:/mydo/backend
./venv/Scripts/python.exe - <<'PYEOF'
import json, tempfile, os, urllib.request, uuid, shutil, time

BASE = "http://localhost:8000"

# --- Login ---
req = urllib.request.Request(
    f"{BASE}/api/auth/login",
    data=json.dumps({"username": "admin", "password": "123456"}).encode(),
    headers={"Content-Type": "application/json"},
)
token = json.loads(urllib.request.urlopen(req).read())["access_token"]

# --- Create minimal EPUB ---
from ebooklib import epub

tmp = tempfile.mkdtemp()
epub_path = os.path.join(tmp, "smoke.epub")
book = epub.EpubBook()
book.set_identifier(f"smoke-{uuid.uuid4().hex}")
book.set_title("Smoke Test")
chapter = epub.EpubHtml(title="Chapter 1", file_name="c1.xhtml", lang="zh")
chapter.content = "<h1>Chapter 1</h1><p>This is a smoke test document.</p>"
book.add_item(chapter)
book.toc = (epub.Link("c1.xhtml", "Chapter 1", "c1"),)
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())
epub.write_epub(epub_path, book)

# --- Upload (multipart) ---
boundary = "----smoke-" + uuid.uuid4().hex
file_data = open(epub_path, "rb").read()
body = (
    f'--{boundary}\r\n'
    'Content-Disposition: form-data; name="file"; filename="smoke.epub"\r\n'
    'Content-Type: application/epub+zip\r\n\r\n'
).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

req = urllib.request.Request(
    f"{BASE}/api/knowledge/upload",
    data=body,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)
resp = json.loads(urllib.request.urlopen(req).read())
doc_id = resp["document_id"]
print(f"UPLOAD OK -> doc id: {doc_id}")

# --- Poll until processing completes ---
for _ in range(30):
    time.sleep(2)
    req = urllib.request.Request(
        f"{BASE}/api/knowledge/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    docs = json.loads(urllib.request.urlopen(req).read())["documents"]
    for d in docs:
        if d["id"] == doc_id:
            status = d["status"]
            chunks = d["chunk_count"]
            print(f"STATUS: {status} | chunks: {chunks} | type: {d.get('file_type')}")
            if status in ("ready", "error"):
                shutil.rmtree(tmp, ignore_errors=True)
                exit(0 if status == "ready" else 1)

shutil.rmtree(tmp, ignore_errors=True)
print("TIMEOUT")
raise SystemExit(2)
PYEOF
```

Expected output:
```
UPLOAD OK -> doc id: <number>
STATUS: ready | chunks: 2 | type: .epub
```

If it fails, check:
- Does the error mention "不支持的文件类型"? The server may have stale code — restart the backend process.
- Is Ollama running? Embedding requires it.
- Check `backend_8000.log` for traceback.

## Supported File Formats (for uploads)

| Format | Extension | Parser | Notes |
|--------|-----------|--------|-------|
| PDF | `.pdf` | PyPDFLoader | Standard |
| Text | `.txt` | TextLoader | UTF-8 |
| Markdown | `.md` | TextLoader | |
| CSV | `.csv` | CSVLoader | |
| Word | `.docx` | Docx2txtLoader | |
| EPUB | `.epub` | EpubLoader (ebooklib) | Converts each chapter to plain text |
| MOBI | `.mobi` | MobiLoader (mobi package) | Translates via mobi → epub/html internally |

Frontend accept attribute: `.pdf,.txt,.md,.csv,.docx,.epub,.mobi`.

## Stopping

To stop everything:

```bash
# Backend: kill the detached python process
tasklist | findstr "uvicorn"   # find PID
taskkill //PID <pid> //F       # kill

# Or restart with start.bat which manages both windows
start.bat   # to start again
```

For the frontend (Vite dev server), Ctrl+C in its terminal window kills it. The browser tab also closes access.

## Common Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| **Can't log in (admin/123456), page loads fine** | Backend (port 8000) is down — the frontend on 5173 still serves, so the page loads but the login request never reaches an API. The most common cause is the backend process having been started as a session-bound background job and reaped when the session ended. | Start the backend with the detached `ProcessStartInfo` recipe above, confirm `curl http://localhost:8000/docs` returns 200, then retry login. |
| `Connection refused` on 8000 | Backend not started or crashed | Restart backend; check logs |
| `"不支持的文件类型"` on upload | Server has stale code (old ALLOWED_EXTENSIONS) | Kill and restart the backend process |
| `Packet sequence number wrong` | SQLAlchemy session reuse across threads | This is handled by the thread-local db pattern in `knowledge.py` — only happens under unusual conditions; restarting fixes it |
| Model loading hangs (>60s) | Embedding model needs to load from disk (HF_HOME=D:/mydo/huggingface_cache) | Normal on first start; wait patiently |
| Ollama not found | LLM inference depends on Ollama | Ensure `ollama serve` is running and model pulled (`ollama pull qwen2.5:7b`) |

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `123456` |
| User | `test` | `test123` |

System URL: `http://localhost:5173`
API Docs: `http://localhost:8000/docs`
