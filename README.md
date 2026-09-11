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
| 向量数据库 | ChromaDB（嵌入式持久化，每个知识库一个独立 collection） |
| 关系数据库 | MySQL 8.0 + Alembic 迁移 |
| 异步任务 | Celery + Redis（失败重试、幂等、启动对账） |
| 前端 | React 18 + Vite + TypeScript + Ant Design 5 |

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
- **混合检索**：向量（语义泛化）+ BM25（精确匹配）双路召回，RRF 融合后去冗余
  - 专治型号 / 错误码 / 专有名词类查询（keyword 类 MRR **0.783 → 0.917**）
- **中文 BM25 二元组分词**：单字切分会命中大量「的/了/是」噪声，实测反而降低召回
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

---

## 🚀 快速启动

### 前置条件

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | |
| Node.js | 18+ | |
| MySQL | 8.0 | |
| Redis | 7+ | 任务队列 broker（**不装也能跑，会自动降级**，见下） |
| Ollama | 最新 | `ollama pull qwen2.5:7b` |

### 1. 配置

```bash
cd backend
cp .env.example .env
# 生成一个真正的 JWT 密钥写进 .env（必做！默认占位值会被拒绝启动）
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. 安装依赖

```bash
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 3. 建库

```sql
CREATE DATABASE rag_knowledge_base CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

表结构由 Alembic 在启动时自动创建，无需手工建表。

### 4. 启动

```bash
# 终端 1：Redis（可选但强烈建议）
docker run -d -p 6379:6379 --name rag-redis redis:7-alpine

# 终端 2：Celery worker（文档处理，独立进程）
cd backend
celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
#                                                          ^^^^^^^^^^^^
#                              Windows 必须加 --pool=solo，否则与事件循环冲突报错

# 终端 3：后端
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 4：前端
cd frontend
npm install && npm run dev
```

访问 `http://localhost:5173`。API 文档：`http://localhost:8000/docs`

> **没有 Redis 也能跑**：任务会自动降级为本地线程并打印告警。
> 该模式**进程重启会丢任务**，仅供本地开发。

### 5. 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | 123456 |

> ⚠️ 生产环境请在首次登录后立即修改密码。

### Docker 一键启动

```bash
cp backend/.env.example backend/.env   # 并填入 JWT_SECRET
docker compose up -d
docker compose ps                      # 六个服务应全部为 healthy
```

包含 mysql / redis / ollama / backend / worker / frontend 六个服务。

**首次启动较慢**，原因与耗时：

| 步骤 | 说明 |
|------|------|
| 拉取基础镜像 | mysql / redis / ollama / python / node / nginx，约 3 GB |
| 构建 backend 镜像 | 含 torch（**用 CPU 版，约 200 MB 而非 CUDA 版的 2 GB+**），约 5-10 分钟 |
| 拉取 qwen2.5:7b | 约 4.7 GB，`docker exec rag-ollama ollama pull qwen2.5:7b` |

**端口分配**（刻意避开宿主机本地环境）：

| 服务 | 宿主机端口 | 说明 |
|------|-----------|------|
| frontend | **5174** | 5173 通常被本地 Vite 占用 |
| backend | 8000 | |
| mysql | **3307** | 3306 通常被宿主机本地 MySQL 占用 |
| ollama | 11434 | |
| redis | 不对外暴露 | 无鉴权，只允许容器网络内访问 |

> 完整的部署记录、踩坑与受限网络下的变通方案，见 [DOCKER_SETUP.md](DOCKER_SETUP.md)。

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
python run_eval.py                 # 自动对比「向量-only」与「混合检索」
python run_eval.py --config hybrid
```

指标：Hit@K / Recall@K / MRR / 拒答正确率。

> 这套评估体系的价值已经被验证过：混合检索初版上线时，
> 主观判断「这是业界最佳实践，必然是提升」，
> 实测 **Hit@5 反而从 83.3% 掉到 80.0%**。
> 定位到根因是中文按单字切分导致的噪声，改为二元组后恢复并超过基线。
> **没有度量，就会把退步当改进交付出去。**

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
