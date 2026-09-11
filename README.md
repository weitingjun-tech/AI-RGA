# RAG 企业级知识库问答系统

基于 LangChain 的 RAG（检索增强生成）知识库问答系统，面向 SaaS 产品技术支持场景。
覆盖**文档治理 → 混合检索 → 可引用生成 → 评估反馈 → 权限审计**的完整闭环。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.11 + FastAPI |
| AI 框架 | LangChain + LangChain Community |
| LLM | 本地 Ollama（`qwen2.5:7b`），可换任意兼容服务 |
| Embedding | `BAAI/bge-small-zh-v1.5`（本地推理，数据不出内网） |
| 精排 | `BAAI/bge-reranker-base`（Cross-Encoder，本地推理） |
| 向量数据库 | ChromaDB（嵌入式持久化，每个知识库一个独立 collection） |
| 关系数据库 | MySQL 8.0 + Alembic 迁移 |
| 异步任务 | Celery + Redis（失败重试、幂等、启动对账） |
| 前端 | React 19 + Vite 8 + TypeScript + Ant Design 6 |
| 质量保障 | pytest + ruff + GitHub Actions（lint / 测试 / 前端构建 / 镜像构建） |

---

## 🌟 核心能力

### 📚 知识库管理
- **多格式解析**：PDF / TXT / MD / CSV / DOCX / EPUB / MOBI（后两者为自研解析器，LangChain 生态无官方 Loader）
- **多知识库隔离**：每个知识库绑定独立向量集合，检索时互不干扰，从根本上避免跨库语料污染
- **中文优化分块**：按中文标点递归切分（500 字 / 50 字重叠）
- **幂等入库**：重复处理同一文档会先清旧向量，不会产生重复内容

### 🔐 权限与合规
- **知识库级 ACL**：用户只能检索被显式授权的知识库
  - **检索前过滤**：无权限的内容从未进入查询范围，不会出现在上下文、日志或模型输入中
  - 管理员始终拥有全部权限；未授权的知识库在列表中不可见
- **审计日志**：记录「谁 / 何时 / 对哪个对象 / 做了什么」+ 来源 IP + 请求链路 ID
- **接口限流**：登录、注册、问答、上传分别限流（Redis 计数，不可用时降级为进程内计数）
- **登录失败锁定**：同一账号连续失败 5 次锁定 15 分钟（`LOGIN_MAX_FAILURES` 可调）
- **上传安全**：扩展名白名单 + **文件头（魔数）校验** + 文件名净化
  - 扩展名可以随便改，文件头不能 —— 把 `.exe` 改名成 `.pdf` 会被拦截
  - 文件名取 basename，`../../../etc/passwd` 会被净化为 `passwd`

### 💬 RAG 问答

**两段式检索**：粗排负责"不漏"，精排负责"排准"。

- **① 粗排 — 混合检索**：向量（语义泛化）+ BM25（精确匹配）双路召回，RRF 融合后去冗余
  - 专治型号 / 错误码 / 专有名词类查询（keyword 类 MRR **0.783 → 0.917**）
  - **中文 BM25 二元组分词**：单字切分会命中大量「的/了/是」噪声，实测反而降低召回
- **② 精排 — Cross-Encoder 重排**（`RERANK_ENABLED`，默认关闭，**原因见下**）
  - 原理：向量检索是把问题和文档**分别**编码再算距离，两者从未"见过面"；
    精排把 (问题, 候选片段) 拼在一起送进模型，让它们在各层注意力里充分交互
  - **拿它当"重排顺序"的手段，实测没有收益**：MRR 0.758 → 0.744
    （30 条样本上属噪声量级），延迟却从 34ms 涨到 8953ms —— CPU 上约 **260 倍**
  - **但它换个用法，效果非常明显**，见下条
- **拒答判定用精排分数，而不是向量分数**
  - 向量分数**分不开**"知识库里到底有没有答案"：无答案问题的最高分均值 **0.53**，
    有答案的 **0.59**，两个分布几乎重叠 —— `RELEVANCE_THRESHOLD` 往哪边调都是错的，
    实测拒答正确率 **0/5**
  - 精排分数则差 4~5 倍（**0.19 vs 0.87**）。取阈值 0.35 后：
    **拒答 0/5 → 4/5**，代价是误伤 1 道正常题（fact 13/13 → 12/13）
  - 净效果 **Hit@5 83.3% → 93.3%（+10 个百分点）**
  - 一句话：**同一个模型，用在排序上没用，用在分类上解决了向量分数解决不了的问题**
  - 默认关闭**不是因为它没效果，而是因为 8.9 秒的延迟**。
    有 GPU 的话这个数字会降到 1 秒内，那时它值得默认打开。
- **多轮检索改写（指代消解）**：用户第二轮问「它支持哪些数据库」，
  原样拿去检索是查不到东西的；先用 LLM 把它改写成不依赖上下文的完整问题再检索
  - **只在问题确实依赖上文时才触发**：改写要额外调一次 LLM（CPU 上 1~3 秒），
    比整个向量检索还慢，无脑改写等于让每次提问都白等
  - 改写**只用于检索**，最终回答的仍是用户原本那句话
- **流式输出**：SSE 实时生成
- **引用溯源**：回答标注来源文档，可核查
- **拒答约束**：知识库无信息时明确说明，禁止编造联系方式等具体信息

### 🔬 可观测与评估
- **检索日志**：每次检索的双路候选、融合数量、去冗余数量、最终 chunk、耗时全量落库
  - 回答「答错了是**没检索到**，还是**检索到了但模型没用**」
- **结构化日志**：`request_id` 贯穿一次请求的所有日志，`LOG_FORMAT=json` 可对接 ELK / Loki
- **链路追踪**：响应头返回 `X-Request-ID`，用户报障时凭它直接还原执行过程
- **黄金测试集**：30 条覆盖 fact / keyword / multihop / refusal 四类场景
- **检索指标**：Hit@K、Recall@K、MRR，支持对照实验验证优化是否真的有效

### 🔁 反馈闭环
- 答案下方 👍/👎，点踩可选原因（不准确 / 不完整 / 过时 / 无关）
- Bad case 归档，每条**附带当次检索明细**，直接定位根因
- 闭环：`生产问题 → 检索日志归因 → 补知识库/改检索 → 进黄金测试集防回归`

### 🚀 部署与运维
- **Alembic 迁移**：表结构变更可追溯、**可回滚**（手写 `ALTER TABLE` 做不到这两点）
- **任务队列**：文档入库由 Celery worker 执行，进程重启不丢任务
  - 失败指数退避重试；worker 崩溃任务自动重投（`acks_late`）
  - **启动对账**：把卡在「排队中/处理中」的僵尸文档重新入队
- **健康检查**：`/api/health`（存活）+ `/api/health/ready`（就绪，逐项探测 MySQL / Chroma / 上传目录）
- **优雅降级**：Redis 不可用时任务降级为本地线程并**打印醒目告警**（绝不静默降级）
- **跨进程缓存失效**：文档更新后，缓存失效通过 Redis 里的共享「语料版本号」广播到所有进程
  - 为什么需要：缓存是进程内的，而文档处理跑在独立的 worker 进程里。
    worker 清自己的缓存，对正在服务的 backend 毫无影响——
    表现为「上传文档后，之前问过的问题在 5 分钟内仍回答未收录」，用户会以为没传上去
  - 做法是把版本号编进缓存键：版本一变，各进程的旧键同时失配，无需互相通知

---

## 🚀 快速启动

项目有两种跑法，**先看这张表选一种**：

| | 🐳 Docker 方式 | 💻 本地开发方式 |
|---|---|---|
| **适合** | 部署、演示、交付 | 改代码（热更新） |
| **前置依赖** | 只需 Docker Desktop | Python / Node / MySQL / Redis / Ollama 全都要装 |
| **启动命令** | 一条 `docker compose up -d` | 双击 `scripts\start-all.bat` |
| **访问地址** | **http://localhost:5174** | **http://localhost:5173** |
| **改代码生效** | 需重新构建镜像 | 保存即生效 |

> ⚠️ **两种方式端口不同是故意的**，这样它们可以同时跑、互不冲突。
> 顺便也可以对照验证：同一份代码在两种环境下行为是否一致。

---

## 🐳 方式一：Docker（推荐）

### 前置条件

| 依赖 | 说明 |
|------|------|
| Docker Desktop | Windows 需开启 WSL2 后端。安装与排障见 [DOCKER_SETUP.md](DOCKER_SETUP.md) |

其它依赖（MySQL / Redis / Ollama / Python / Node）**全部打包在容器里**，不需要在宿主机安装。

### 1. 配置（仅首次）

```bash
cp backend/.env.example backend/.env
```

然后生成一个真正的 JWT 密钥填进 `backend/.env` 的 `JWT_SECRET=`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> 这步**不能跳过**：`APP_ENV=production` 下如果 `JWT_SECRET` 未设置或仍是
> 占位值，后端会**拒绝启动**。这是刻意的——默认密钥等于把管理员令牌的签发权公开。

### 2. 启动

```bash
docker compose up -d
docker compose ps          # 等六个服务全部变成 healthy
```

### 3. 拉取模型（仅首次）

```bash
docker exec rag-ollama ollama pull qwen2.5:7b
```

没有模型时系统能检索但无法生成回答。

### 4. 访问

**http://localhost:5174** · 账号 `admin` / `123456`

### 首次启动要多久

| 步骤 | 体积 | 说明 |
|------|------|------|
| 拉取基础镜像 | ~3 GB | mysql / redis / ollama / python / node / nginx |
| 构建 backend 镜像 | ~200 MB | **torch 用 CPU 版**（CUDA 版是 2 GB+，容器没 GPU，纯属死重量） |
| 拉取 qwen2.5:7b | ~4.7 GB | 第 3 步 |

### 常用命令

```bash
docker compose ps                      # 状态（全部 healthy 才算正常）
docker compose logs -f backend         # 跟踪某个服务日志
docker compose restart backend         # 重启单个服务（改了 .env 后需要）
docker compose up -d --build backend   # 改了后端代码后重建
docker compose down                    # 停止（数据保留在卷里）
docker compose down -v                 # 停止并删除数据（谨慎）
```

### 端口分配

| 服务 | 宿主机端口 | 说明 |
|------|-----------|------|
| frontend | **5174** | 5173 留给本地 Vite |
| backend | 8000 | |
| mysql | **3307** | 3306 留给宿主机本地 MySQL |
| ollama | 11434 | |
| redis | **不暴露** | 无鉴权，只允许容器网络内访问 |

---

## 💻 方式二：本地开发

适合改代码——Vite 和 uvicorn 都支持热更新，保存即生效。

### 前置条件

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | |
| Node.js | **22.12+** | 低于此版本 Vite 8 会构建失败 |
| MySQL | 8.0 | |
| Redis | 7+ | 任务队列 broker（**不装也能跑**，见下） |
| Ollama | 最新 | `ollama pull qwen2.5:7b` |

Redis 本项目提供**免安装便携版**（不需要管理员权限、不注册系统服务）：

```bash
# 已放在 D:\tools\redis，直接双击 scripts\start-redis.bat 即可
```

> **没有 Redis 也能跑**：任务会自动降级为本地线程**并打印醒目告警**。
> 该模式进程重启会丢任务，仅供本地开发，不要用于演示。

### 1. 配置

```bash
cd backend
cp .env.example .env
# 同样要生成 JWT_SECRET（开发环境留空会随机生成，但重启后需重新登录）
```

### 2. 安装依赖

```bash
cd backend
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -r requirements.txt

cd ../frontend
npm install
```

### 3. 建库

```sql
CREATE DATABASE rag_knowledge_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

表结构由 Alembic 在启动时自动创建，**不需要手工建表**。

### 4. 启动

**推荐：双击 `scripts\start-all.bat`** —— 一条命令拉起全部四个服务，
自带前置检查和健康验证。

它做的事（也可手动逐个启动）：

```bash
# ① Redis（先启动，worker 要连它）
scripts\start-redis.bat

# ② Celery worker —— 文档处理，独立进程
cd backend
venv\Scripts\python.exe -m celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
#                                                                               ^^^^^^^^^^^^
#                            Windows 必须加 --pool=solo，否则与 asyncio 事件循环冲突会直接报错

# ③ 后端（等模型加载约 20-30 秒）
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ④ 前端
cd frontend
npm run dev
```

**启动顺序有依赖**，不能乱：Redis → worker → 后端 → 前端。
worker 启动时会连 broker，后端启动时会连 MySQL 并执行数据库迁移。

### 5. 访问

**http://localhost:5173** · API 文档 http://localhost:8000/docs

---

## 🔑 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | 123456 |

> ⚠️ **生产环境请在首次登录后立即修改密码。**

**注意**：系统启动只预置 `admin` 一个账号。自行注册的用户
**默认没有任何知识库权限**（ACL 默认拒绝），需要管理员到
「知识库管理 → 授权管理」里分配后才能检索。

---

## 🔍 起不来怎么办

按顺序排查，多数问题在前两步就能定位：

```bash
# 1. 服务到底在不在跑
docker compose ps                                    # Docker 方式
netstat -ano | findstr ":5174 :8000 :5173"           # 看端口有没有被监听

# 2. 依赖是否健康（逐项探测 MySQL / Chroma / 上传目录）
curl http://localhost:8000/api/health/ready
#    期望 {"status":"ok","checks":{"mysql":"ok","chroma":"ok","upload_dir":"ok"}}

# 3. 看日志
docker compose logs --tail=50 backend                 # Docker 方式
```

| 现象 | 常见原因 |
|------|---------|
| 页面能开，但**点登录没反应** | CORS 白名单没含当前前端端口。改 `docker-compose.yml` 的 `CORS_ORIGINS` 后 `docker compose up -d backend` |
| 登录返回 **429** | 触发了限流。等 1 分钟；频繁测试可调高 `RATE_LIMIT_LOGIN` |
| 登录返回 429「账号已锁定」 | 同账号连错 5 次，等 15 分钟或清 Redis 的 `loginfail:*` |
| 文档一直「**排队中**」 | Celery worker 没启动，或连不上 Redis |
| 上传响应 `queue_mode: thread` | Redis 不可用，任务已降级（生产应设 `TASK_QUEUE_MODE=celery` 禁止降级） |
| 用户看不到任何知识库 | ACL 默认拒绝，需管理员授权 |
| 后端容器反复重启 | `JWT_SECRET` 没填，生产模式拒绝启动 |

---

## 🔧 环境变量

完整清单见 [`backend/.env.example`](backend/.env.example)，关键项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_ENV` | development | `production` 会强制校验 JWT_SECRET、关闭 `/docs`、隐藏异常细节 |
| `JWT_SECRET` | — | **必填**，≥32 字符。生产环境留空将拒绝启动 |
| `EMBEDDING_MODEL` | BAAI/bge-small-zh-v1.5 | |
| `KB_ACL_ENABLED` | true | 关闭后所有登录用户可访问全部知识库（仅限单机调试） |
| `TASK_QUEUE_MODE` | auto | `auto` / `celery`（**生产必选**）/ `thread` |
| `RUN_MIGRATIONS_ON_STARTUP` | true | 多副本生产环境应关闭，改由发布流水线执行迁移 |
| `LOG_FORMAT` | text | `json` 便于日志采集系统解析 |
| `RATE_LIMIT_CHAT` | 30/minute | 问答接口限流 |

---

## 📁 项目结构

```
mydo/
├── backend/
│   ├── app/
│   │   ├── main.py                 # 应用入口：迁移、对账、中间件、异常处理
│   │   ├── config.py               # 集中配置（含生产环境强校验）
│   │   ├── celery_app.py           # Celery 实例与可靠性配置
│   │   ├── models/                 # ORM 模型
│   │   │   ├── kb_permission.py    # 知识库授权（ACL）
│   │   │   └── audit_log.py        # 审计日志
│   │   ├── api/
│   │   │   ├── auth.py             # 登录（限流 + 失败锁定）
│   │   │   ├── chat.py             # 问答（权限收敛 + 检索日志）
│   │   │   ├── knowledge.py        # 知识库/文档/授权管理
│   │   │   └── admin.py            # 审计日志查询
│   │   ├── services/
│   │   │   ├── rag_service.py      # 检索核心（混合检索 / RRF / 去冗）
│   │   │   ├── kb_service.py       # 文档解析与入库（幂等）
│   │   │   ├── permission_service.py  # ACL：检索前过滤
│   │   │   ├── task_dispatch.py    # 任务投递（Celery + 降级）
│   │   │   └── audit_service.py    # 审计写入（失败不影响主流程）
│   │   ├── tasks/document_tasks.py # Celery 任务（重试 / 幂等）
│   │   └── utils/
│   │       ├── file_security.py    # 文件名净化 + 魔数校验
│   │       ├── rate_limit.py       # 限流与登录锁定
│   │       ├── request_context.py  # request_id 上下文
│   │       └── logging_config.py   # 日志（text / json）
│   ├── migrations/                 # Alembic 迁移
│   │   └── versions/
│   │       ├── 0001_baseline.py
│   │       └── 0002_enterprise_hardening.py
│   └── requirements.txt
├── frontend/src/
│   ├── config.ts                   # API 地址（构建时注入）
│   ├── pages/admin/
│   │   ├── KbManage.tsx            # 文档管理 + 授权管理
│   │   └── AuditLogs.tsx           # 审计日志
│   └── ...
├── eval/                           # 检索评估
│   ├── golden_set.json             # 30 条黄金测试集
│   └── run_eval.py
└── docker-compose.yml
```

---

## 🗄️ 数据库迁移

```bash
cd backend

alembic current                    # 当前版本
alembic history                    # 迁移历史
alembic upgrade head               # 升级到最新
alembic downgrade -1               # 回滚一个版本
alembic revision --autogenerate -m "描述"   # 改完模型后生成迁移
alembic check                      # 校验模型与数据库是否一致
```

**改表结构后务必**：`--autogenerate` → **人工检查生成的脚本** → `upgrade` → `alembic check` 确认无差异。

> `--autogenerate` 是辅助工具不是权威。它识别不出列重命名（会生成「删旧列 + 加新列」，
> 导致数据丢失），也可能漏掉数据迁移。**生成的脚本必须逐行看过再执行。**

---

## 📊 检索评估

```bash
cd eval
python run_eval.py                  # 依次跑三档并对比（默认）
python run_eval.py --config hybrid
python run_eval.py --config rerank
```

指标：Hit@K / Recall@K / MRR / 拒答正确率。

**为什么是"三档递进"而不是两档对比**：向量 → 加 BM25 → 加精排，
每加一层都要单独量一次贡献。只看首尾两个数，无法回答
「到底是哪一层起了作用」「哪一层白加了」——而后者恰恰最容易发生。

### 实测结果（30 条黄金集）

| 配置 | Hit@5 | Recall@5 | MRR | 平均延迟 |
|------|-------|----------|-----|---------|
| 向量检索（基线） | 83.3% | 78.9% | 0.757 | 216ms |
| 混合检索 + 去冗余 | 83.3% | 77.8% | 0.758 | **34ms** |
| 上者 + 精排（含拒答过滤） | **93.3%** | **87.2%** | **0.867** | 8953ms |

按问题类型看 MRR（这才是分档跑的意义）：

| 类型 | 向量 | 混合 | +精排 |
|------|------|------|-------|
| keyword（型号/错误码） | 0.783 | **0.917** | 0.917 |
| fact | 0.923 | 0.904 | 0.885 |
| multihop | 1.000 | 0.917 | 0.833 |
| **拒答正确率** | 0/5 | 0/5 | **4/5** |

**净变化逐项拆开**（精排 vs 纯混合检索）：

| 类型 | 命中数 | 变化 | 说明 |
|------|--------|------|------|
| refusal | 0/5 → 4/5 | **+4** | 拒答被修好 |
| fact | 13/13 → 12/13 | **−1** | 误伤了一道正常题 |
| keyword / multihop | 无变化 | 0 | |
| **合计** | 25/30 → **28/30** | **+3** | Hit@5 +10 个百分点 |

**能从表里读出的三件事**：

1. 混合检索的收益集中在 keyword 类（0.783 → 0.917），与设计意图一致；
   fact 类反而略降 —— 换到的是总体更稳，不是每项都涨。
2. **精排对"排序"本身是负收益**：多跳问题 1.000 → 0.833。
   原因可解释——逐条打分的模型面对"答案要跨两个片段"的问题时，
   单独看哪个片段都不够对口。延迟代价却是 260 倍。
3. **真正的收益全部来自"拒答分类"**：+4 换 −1，净 +3。
   这也说明**为什么必须逐项拆开看**：只看总分 "+10 个百分点"，
   会以为精排让检索变准了；实际它让排序变差了，只是拒答修好了足够多。

> 这套评估体系的价值已经被验证过两次。
> 第一次：混合检索初版上线时主观判断「这是业界最佳实践，必然是提升」，
> 实测 **Hit@5 反而从 83.3% 掉到 80.0%**，根因是中文按单字切分引入噪声，
> 改为二元组后恢复并超过基线。
> 第二次就是上面的精排：它作为排序手段应当被否掉，作为分类手段才该保留。
> 不做评估的话，这两种用法根本区分不开。
> **没有度量，就会把退步当改进交付出去。**

---

## ✅ 测试与 CI

```bash
cd backend
pip install -r requirements-dev.txt   # pytest + ruff

pytest                                 # 运行全部测试
pytest --cov=app --cov-report=term     # 带覆盖率
ruff check app tests ../eval           # 静态检查
```

测试按「测什么」分层，而不是按文件来源分：

| 文件 | 覆盖内容 |
|------|---------|
| `test_acl.py` | 知识库权限收敛 —— **含越权漏洞的回归测试** |
| `test_auth_api.py` | 认证接口全链路（登录 / 锁定 / 刷新 / 改密 / 审计） |
| `test_file_security.py` | 文件名净化 + 文件头魔数校验 |
| `test_retrieval.py` | 中文分词 / RRF 融合 / 去冗余 / 上下文构建 |
| `test_rerank.py` | 精排重排逻辑，以及**模型不可用时的降级** |
| `test_query_rewrite.py` | 指代消解触发条件与失败回退 |
| `test_rate_limit.py` | 限流、账号锁定、组件故障时的放行 |
| `test_config.py` | 生产环境 JWT 强校验、默认值的安全性 |

**为什么用 SQLite 内存库而不是 Mock**：权限过滤是靠 SQL 的 `WHERE` 实现的，
用 Mock 测等于什么都没测——Mock 会乖乖返回你让它返回的东西。
SQLite 提供真实的查询语义，才测得出「条件写错了」这类问题。

**为什么接口测试要单独起一个 FastAPI 实例**：`app.main` 的启动钩子会执行
数据库迁移和任务对账，测试不该有这些副作用。

CI（GitHub Actions，`push` / `PR` 触发）跑四件事：

| 任务 | 作用 |
|------|------|
| ruff | 语法错误 + 未定义名 + 死导入 |
| pytest | 全部测试（含覆盖率报告） |
| tsc + vite | 前端类型检查与打包 |
| docker build | **验证 Dockerfile 本身可用**——这件事靠读代码验证不了 |

> 写测试的过程中揪出了两个真实缺陷，都已修复：
> `.env` 里的密码超过 72 **字节**时注册接口报 500（bcrypt 的字节上限，
> 而中文一个字占 3 字节，`max_length=100` 是按字符算的，根本挡不住）；
> 以及 `passlib` 是个从未被调用、却已与新版 bcrypt 不兼容的死依赖。

---

## 🔒 生产部署检查清单

- [ ] `APP_ENV=production`
- [ ] `JWT_SECRET` 已设置为随机值（≥32 字符）
- [ ] `TASK_QUEUE_MODE=celery`（禁止降级）
- [ ] `RUN_MIGRATIONS_ON_STARTUP=false`，迁移由发布流水线执行（多副本时）
- [ ] `LOG_FORMAT=json`，日志已接入采集系统
- [ ] `CORS_ORIGINS` 收敛到实际域名
- [ ] Redis 开启持久化（AOF），否则重启丢队列
- [ ] MySQL 使用独立账号，不要用 root
- [ ] 修改默认管理员密码
- [ ] 按组织架构梳理知识库授权（迁移时为保持兼容，存量用户默认获得了原有范围）

---

## 📄 更新日志

版本改动详情（含每个版本的优化点与纠错点）见 [CHANGELOG.md](CHANGELOG.md)。
