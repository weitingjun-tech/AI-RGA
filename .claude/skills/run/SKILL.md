# /run — Launch the RAG Knowledge Base System

This skill covers starting the **full stack** — Redis (task broker), Celery worker (document
processing), backend (FastAPI, port 8000), and frontend (Vite, port 5173) — verifying they are
healthy, and optionally running an end-to-end smoke test.

## Prerequisites

| Requirement | How to check | Required? |
|---|---|---|
| MySQL 8.0+ | `mysql -u root -p` | **必须** |
| Ollama running | `curl -s http://localhost:11434/api/tags` | **必须**（生成回答） |
| Python 3.11+ with venv | `./backend/venv/Scripts/python.exe --version` | **必须** |
| Node.js 18+ | `node --version` | **必须**（前端） |
| Redis | `D:/tools/redis/redis-cli.exe ping` | 建议（见下） |

### Redis 是"建议"而非"必须"的原因

文档入库任务在没有 Redis 时会**自动降级为本地线程**并打印醒目告警，
系统仍能正常上传和问答。但降级模式下：
- 进程重启会**丢失未完成的任务**，文档可能永久卡在「处理中」
- 没有跨进程重试

所以：**演示/开发可以没有 Redis，但看到降级告警时应该知道它的代价。**

`AUDIT_LOG_ENABLED` / `RATE_LIMIT_ENABLED` 同样会因 Redis 缺失而降级
（限流退化为进程内计数，多 worker 时配额会被放大）。

前四项必须满足才能启动。缺任何一项，报告是哪一项并停止。

## Startup

启动顺序有依赖：**Redis → Celery worker → 后端 → 前端**。
Celery worker 启动时会连 broker，Redis 没起来它会一直重试。

### 0a. Start Redis（便携版，不需要管理员权限）

```bash
cd /d/tools/redis && ./redis-server.exe redis-rag.conf
```

或双击 `scripts/start-redis.bat`（会打印数据目录和停止方式）。

验证：

```bash
D:/tools/redis/redis-cli.exe ping        # 期望 PONG
D:/tools/redis/redis-cli.exe info persistence | grep aof_enabled   # 期望 aof_enabled:1
```

**AOF 必须为 1**。默认的 RDB 是周期快照，Redis 崩溃会丢掉最近几秒的数据——
对缓存无所谓，对**任务队列**意味着用户上传的文档凭空消失。

### 0b. Start the Celery Worker（文档处理）

```bash
cd d:/mydo/backend
./venv/Scripts/python.exe -m celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
```

或双击 `scripts/start-celery.bat`。

**Windows 必须加 `--pool=solo`**：Celery 默认的 prefork 进程池与 asyncio 事件循环冲突，
不加会直接报错。Linux/macOS 用默认值即可，并发数由 `--concurrency` 控制。

启动成功的标志（日志里应看到）：

```
[tasks]
  . documents.process
[INFO/MainProcess] Connected to redis://localhost:6379/0
[INFO/MainProcess] celery@<主机名> ready.
```

`--pool=solo` 是**单进程串行**执行。批量上传几十个文档时会排队，
这是预期行为——要看队列积压情况可以观察文档状态里的 `queued` 数量。

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

Wait ~15 seconds for embedding model initialization, then verify.

**用就绪探针而不是 `/docs`**——`/docs` 只能说明进程活着，
`/api/health/ready` 会逐项探测 MySQL / Chroma / 上传目录，任一不可用返回 503：

```bash
curl -s http://localhost:8000/api/health/ready
```

期望输出：

```json
{"status":"ok","checks":{"mysql":"ok","chroma":"ok","upload_dir":"ok"}}
```

若 `status` 为 `degraded`，`checks` 里会指出是哪一项出了问题。

> 注意：`APP_ENV=production` 时 `/docs` 会被关闭（返回 404），
> 这是有意的——接口文档会暴露完整的内部分支结构。用 `/api/health` 做存活检查。

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

### 3. Verify Everything Is Running

```bash
curl -s -o /dev/null -w "backend:  %{http_code}\n" http://localhost:8000/api/health
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173/
D:/tools/redis/redis-cli.exe ping                       # PONG
netstat -ano | grep ":6379.*LISTENING"                  # Redis 端口
```

Backend 与 frontend 都应返回 `200`。

检查 Celery worker 是否在跑：

```bash
cd d:/mydo/backend
./venv/Scripts/python.exe -m celery -A app.celery_app:celery_app inspect ping
```

期望：`pong`。没有响应说明 worker 没起来或连不上 broker——
此时上传仍然"成功"，但任务会降级为本地线程执行。

**同时确认后端日志里没有降级告警**（有的话说明 Redis 没连上）：

```bash
grep -i "降级\|Redis 不可用" backend_8000.log
```

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
# queue_mode 告诉我们任务走到了哪条路径：
#   "celery" = 正常，进了 Redis 队列，由 worker 处理
#   "thread" = 降级，Redis 不可用，本地线程处理（重启会丢任务）
print(f"UPLOAD OK -> doc id: {doc_id} | queue_mode: {resp.get('queue_mode')}")

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
UPLOAD OK -> doc id: <number> | queue_mode: celery
STATUS: queued | chunks: 0 | type: .epub
STATUS: processing | chunks: 0 | type: .epub
STATUS: ready | chunks: 2 | type: .epub
```

状态流转 `queued → processing → ready`：
- `queued` = 已入队，等 worker 领取（没有这一步说明没走队列）
- `processing` = worker 正在解析+向量化
- `ready` = 完成，可被检索

**若 `queue_mode` 是 `thread`**：说明 Redis 不可用，任务走了降级路径。
功能上能用，但进程重启会丢任务——需要启动 Redis 与 worker。

If it fails, check:
- Does the error mention "不支持的文件类型"? The server may have stale code — restart the backend process.
- 文档类型伪装会被拦（文件头校验）。上传真实文件而非改名文件。
- Is Ollama running? Embedding 需要它加载模型。
- 一直卡在 `queued` 不动 → Celery worker 没启动，或连不上 Redis。
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

按启动的**逆序**停止：前端 → 后端 → Celery worker → Redis。

```bash
# 前端：在它的终端窗口按 Ctrl+C

# 后端：找到监听 8000 的 PID 并杀（venv 会再起一个子进程，所以要按端口找而不是按进程名）
netstat -ano | grep ":8000.*LISTENING"      # 取最后一列 PID
taskkill //PID <pid> //T //F                # /T 连同子进程一起杀

# Celery worker：Ctrl+C；或按端口找不到，用任务管理器结束对应窗口
# Redis：关闭它的窗口即可。排队中的任务已写入 AOF，下次启动自动恢复。
```

**不要用 `taskkill /IM python.exe /F` 这种按进程名批量杀的方式**——
它会杀掉机器上所有 Python 程序，包括你自己的其它工作。

> 停止 Redis 前无需担心丢数据：AOF 每秒落盘一次，最多丢 1 秒。
> 想确认的话看 `D:\tools\redis\data\appendonly.aof` 的文件时间。

## Common Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| **Can't log in (admin/123456), page loads fine** | Backend (port 8000) is down — the frontend on 5173 still serves, so the page loads but the login request never reaches an API. The most common cause is the backend process having been started as a session-bound background job and reaped when the session ended. | Start the backend with the detached `ProcessStartInfo` recipe above, confirm `curl http://localhost:8000/docs` returns 200, then retry login. |
| `Connection refused` on 8000 | Backend not started or crashed | Restart backend; check logs |
| `"不支持的文件类型"` on upload | Server has stale code (old ALLOWED_EXTENSIONS) | Kill and restart the backend process |
| `Packet sequence number wrong` | SQLAlchemy session reuse across threads | This is handled by the thread-local db pattern in `knowledge.py` — only happens under unusual conditions; restarting fixes it |
| Model loading hangs (>60s) | Embedding model needs to load from disk (HF_HOME=D:/mydo/huggingface_cache) | Normal on first start; wait patiently |
| Ollama not found | LLM inference depends on Ollama | Ensure `ollama serve` is running and model pulled (`ollama pull qwen2.5:7b`) |
| 文档一直卡在「排队中」 | Celery worker 没启动，或连不上 Redis | `redis-cli ping` 确认 Redis；启动 worker（`--pool=solo`） |
| 上传响应 `queue_mode: thread` | Redis 不可用，任务已降级 | 启动 Redis 与 worker；生产环境应设 `TASK_QUEUE_MODE=celery` 禁止降级 |
| 登录返回 429「操作过于频繁」 | 触发了 IP 限流（默认 10 次/分钟） | 等待 1 分钟。频繁测试时可临时调高 `RATE_LIMIT_LOGIN` |
| 登录返回 429「账号已锁定」 | 同账号连续失败 5 次 | 等待 `LOGIN_LOCKOUT_MINUTES`（默认 15 分钟），或清 Redis 的 `loginfail:*` 键 |
| 用户看不到任何知识库 | ACL 默认拒绝，未授权 | 管理员到「知识库管理 → 授权管理」分配；或临时 `KB_ACL_ENABLED=false` |
| 改了表结构但接口报字段不存在 | 没生成/执行迁移 | `alembic revision --autogenerate -m "..."` → 检查脚本 → `alembic upgrade head` |
| `alembic.ini` 读取报 UnicodeDecodeError | 用了非 ASCII 字符（Windows 下按 GBK 读） | 该文件保持纯 ASCII，中文说明写在 `migrations/env.py` 里 |

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `123456` |

系统启动时只会预置 `admin` 一个账号，普通用户需自行注册。
（注册的账号默认**没有任何知识库权限**，需要管理员在「授权管理」里分配。）

System URL: `http://localhost:5173`
API Docs: `http://localhost:8000/docs` （`APP_ENV=production` 时关闭）
