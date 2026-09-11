# 更新日志 (Changelog)

本文件记录每个版本的**详细优化点与纠错点**。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

分类说明：
- ✨ **新增** — 新功能
- 🚀 **优化** — 性能、质量、体验改进
- 🐛 **修复** — 纠正的缺陷（含问题现象、根因、影响）
- 🏗️ **工程** — 构建、依赖、工具链
- ⚠️ **已知局限** — 尚未解决的问题（如实记录）

---

## [未发布]

### 🏗️ 工程
- **新增 `/save` skill**：把「更新改动详情 → 提交 → 写规范 commit message → 推送 → 打版本标签」
  固化为可复用流程。skill 中固化了本项目踩坑得出的约束：必须用 SSH（HTTPS 被网络阻断）、
  不把令牌粘贴进对话、提交前检查 `.env`、工作区干净时不造空提交
- **新增 `CHANGELOG.md`（本文件）**：要求每次保存版本时同步更新，按分类记录改动详情
  - 🐛 修复类条目**必须写全「现象 / 根因 / 影响 / 修复」四段**
  - 🚀 优化类条目**必须带量化对比**（优化前 → 优化后），无实测数据时不编造
  - ⚠️ 已知局限**如实记录**，含原因与改进方向
  - 已打标签的历史版本只追加、不修改

---

## [未发布]

### ✨ 新增
- **Redis 便携版部署**：本机已装 `D:\tools\redis`（免安装、无需管理员权限）。
  配置开启了 **AOF 持久化**——这里存的是任务队列而非缓存，
  默认的 RDB 周期快照会丢最近几秒数据，对队列意味着"上传的文档凭空消失"
- **Celery 完整链路实测通过**（补上 v1.1.0 中"未实测"的一项）：
  上传返回 `queue_mode=celery`，状态流转 `queued → processing → ready`，
  worker 日志与 Redis 中的 `celery-task-meta-*` 键均确认任务确实经过 broker

### 🐛 修复

**1. `.bat` 脚本用 UTF-8 保存导致中文 Windows 下无法运行**
- **现象**：运行 `enable-wsl.bat` 报
  `'噯澶囧ソ鏃舵妸鏈哄櫒閲嶅惎鎺夈€?' 不是内部或外部命令`，
  随后一连串「系统找不到指定的路径」
- **根因**：cmd.exe 按**系统 ANSI 代码页**读取 `.bat` 文件，中文 Windows 下是 GBK。
  文件存成 UTF-8 后中文被解码成乱码，**乱码又破坏了批处理的语法结构**，
  于是 `REM` 注释和 `for` 循环被当成命令去执行
- **影响**：三个 `.bat`（start-redis / start-celery / enable-wsl）**全部无法运行**
- **修复**：改用 GBK 编码 + CRLF 换行写入
- **同类问题**：`alembic.ini` 早前也因同样的原因失败过
  （Python 用 locale 编码读取配置文件，中文注释导致 UnicodeDecodeError）。
  **教训：配置文件与批处理脚本一律避开非 ASCII，或必须按目标编码写入**

**2. `requirements.txt` 漏声明 `beautifulsoup4`（Docker 部署才暴露）**
- **现象**：容器启动即崩溃 —— `ModuleNotFoundError: No module named 'bs4'`
- **根因**：`kb_service.py` 用 `BeautifulSoup` 解析 EPUB 正文，但该包**没有任何其它依赖会引入它**
  （`pip show beautifulsoup4` 的 `Required-by` 为空）。本地开发机上当初是手动装的，
  所以从未写进 `requirements.txt`
- **影响**：**任何一次干净部署都会失败**。这是典型的「本地能跑、交付即崩」——
  本地环境的隐式状态掩盖了缺失的依赖声明
- **修复**：显式声明 `beautifulsoup4==4.15.0` + `soupsieve==2.9.2`（连依赖一起锁版本）
- **发现方式**：在容器内静态扫描全部 `import` 与已安装包做比对，确认只缺这一个

**3. 前端容器健康检查恒为 unhealthy**
- **现象**：`docker compose ps` 显示前端 `unhealthy`，但宿主机访问返回 200，服务是好的
- **根因**：健康检查写的是 `localhost`，而容器内 `/etc/hosts` 把 `localhost` 解析到
  IPv6 的 `::1`，nginx 只监听 IPv4 的 `0.0.0.0:5173`，于是 wget 被拒
- **影响**：编排层无法正确判断服务状态；`--wait` 会失败，自动扩缩容会误判
- **修复**：改用 `127.0.0.1`

**4. Celery worker 容器恒为 unhealthy**
- **现象**：worker 正常运行（日志显示 `Connected to redis://...` 并注册了任务），却报 unhealthy
- **根因**：worker 与 backend **共用同一个镜像**，而镜像层的 `HEALTHCHECK` 探测的是
  backend 的 HTTP 端点 `/api/health/ready` —— worker 根本不提供 HTTP 服务
- **影响**：健康检查形同虚设，编排层会误判 worker 不可用
- **修复**：在 compose 里为 worker 覆盖健康检查，改用 Celery 自身的
  `inspect ping -d celery@$HOSTNAME`。这个检查同时验证三件事：
  worker 进程活着、能连上 broker、能响应消息

**5. 构建上下文未排除依赖目录**
- **现象**：Docker 构建每次都要传输 **1.01 GB** 上下文
- **根因**：缺少 `.dockerignore`，`venv/`（Windows 版依赖，含 .exe/.pyd）、
  `chroma_data/`、`uploads/` 全被打包发给构建守护进程
- **影响**：构建慢；且 Windows 的 venv 拷进 Linux 容器完全不可用
- **修复**：补 `.dockerignore`，上下文 **1.01 GB → 908 B**

**6. 容器内 torch 装成了 CUDA 版**
- **现象**：镜像体积异常大，构建耗时长
- **根因**：PyPI 上 Linux 版 `torch` 默认捆绑 CUDA 运行时（2 GB+），
  而容器根本不挂 GPU，那些库纯属死重量
- **修复**：改从 PyTorch 官方 CPU 索引安装 —— **2 GB+ → 196 MB**

**7. 依赖解析陷入回溯，构建无法完成**
- **现象**：`pip install` 连续下载了 **25 个不同版本的 transformers**，
  跑了 25 分钟仍未收敛
- **根因**：torch 未锁版本，装到了 2.14.0，与 `sentence-transformers==3.3.1`
  的约束冲突，pip 开始暴力试错
- **修复**：从**本地已验证可运行的环境**导出 `pip freeze`，
  锁定 `transformers==4.46.3` / `tokenizers==0.20.3` /
  `huggingface_hub==0.36.2` / `safetensors==0.8.0`，并锁死 `torch==2.13.0`
- **验证**：锁定后 transformers 只下载 2 次即完成

**8. 前端镜像的 Node 版本不满足构建要求**
- **现象**：容器内 `npm run build` 报
  `SyntaxError: The requested module 'node:util' does not provide an export named 'styleText'`
- **根因**：Dockerfile 用 `node:18-alpine`，而项目用的是 Vite 8，
  其底层打包器 rolldown 依赖 `node:util` 的 `styleText`（Node 20.12 才加入）
- **影响**：本地开发机是 Node 24 所以完全不会暴露，只在容器里出现
- **修复**：改用 `node:22-alpine`，并在 `package.json` 补 `engines` 声明，
  让这类错误在 `npm ci` 阶段就暴露

**9. 改了前端端口却没改 CORS 白名单 —— 表现为「点登录没反应」**
- **现象**：浏览器打开 `localhost:5174`，输入 admin/123456 点登录，**页面毫无反应**，
  也不报错。而 curl 直接打接口一切正常
- **根因**：容器部署把前端端口从 5173 改成 5174（5173 留给本地 Vite），
  但后端的 `CORS_ORIGINS` 仍是 `http://localhost:5173,http://localhost:3000`。
  5174 → 8000 属于跨域，浏览器**直接丢弃**响应，前端连错误信息都拿不到
- **影响**：整个系统在浏览器里不可用，且**没有任何可见的错误提示**——
  这是最难排查的一类故障：服务端全绿、日志无异常、接口单独测都通过
- **修复**：在 compose 里为 backend 显式设置 `CORS_ORIGINS`（含 5174），
  并注释说明换域名部署时要同步修改
- **验证方式**：带 `Origin` 头模拟浏览器请求全部 9 个前端会用到的接口
  （含 SSE 流式问答与 401 时的 token 刷新），并确认未授权源仍被拒绝
- **教训**：改端口这类改动，**必须按用户实际路径（浏览器）验证**，
  只 curl 后端接口会完全错过前后端衔接处的问题

### 🏗️ 工程
- 新增 `scripts/start-redis.bat`、`scripts/start-celery.bat`（含 Redis 可达性预检）
- 新增 `scripts/enable-wsl.bat`：启用 WSL2 所需功能，含管理员权限自检
- 新增 `DOCKER_SETUP.md`：Docker 部署准备清单，标注每步「谁执行」与预期问题
- **Docker 部署落地**（`docker-compose.yml`）：
  - backend 镜像显式命名，worker 复用同一镜像而非各构建一份
  - 补 `backend/.dockerignore`、`frontend/.dockerignore`
  - 基础镜像改用 `node:22-alpine`
  - pip 源与 torch 源提为构建参数（`PIP_INDEX_URL` / `TORCH_INDEX_URL` / `TORCH_VERSION`）
  - 后端镜像改以非 root 用户（uid 1000）运行
  - MySQL 宿主端口映射到 **3307**（3306 通常被宿主机本地 MySQL 占用；
    容器之间仍走 `mysql:3306`，不受影响）
  - **`uploads` / `chroma_data` 改用具名卷**而不是绑定宿主机目录 ——
    否则容器化的空 MySQL 会与宿主机既有的向量数据对不上，
    产生「向量在、文档表没有」的孤儿数据
  - 新增 `docker-compose.workarounds.yml`：受限网络环境下的变通
    （宿主机 Redis 桥接 + 前端健康检查覆盖），网络恢复后去掉 `-f` 参数即可回归标准部署
- **前端 `index.html` 清理模板残留**：标题由 Vite 默认的 `frontend` 改为
  「RAG 知识库问答系统」；`lang="en"` 改为 `lang="zh-CN"`
  （影响中文断词换行、语音朗读与搜索引擎归类）；补 `description` 与 `theme-color`
- `/run` skill 更新为**四进程架构**（Redis → Celery worker → 后端 → 前端）：
  - 新增 Redis / worker 的启动与验证步骤
  - 健康检查改用 `/api/health/ready`（逐项探测依赖），不再用 `/docs`
  - 冒烟测试新增 `queue_mode` 判定与 `queued` 状态说明
  - 排障表补充 Redis / 限流 / 锁定 / ACL / 迁移条目
  - **修正停止流程**：明确禁止 `taskkill /IM python.exe /F` 这类按进程名批量杀
    （会误杀机器上所有 Python 程序）

### ⚠️ 已知局限
- **Docker 仍未部署**：本机为 Windows 11 家庭版，Docker Desktop 只能走 WSL2 后端，
  而启用 WSL2 需要管理员权限 + **重启电脑**。步骤已完整写在 `DOCKER_SETUP.md`
- Docker Hub（`registry-1.docker.io`）在本网络下不可达，
  部署前**必须**先配镜像加速，否则 `docker compose up` 会卡在拉镜像

---

## [v1.1.0] - 2026-09-11

企业级落地加固：补齐**权限、可靠性、迁移、合规**四块工程短板。

> 这一版的判断依据是：v1.0.0 之后算法层（检索、评估、反馈）已经追平主流开源项目，
> 但企业采购看的不是算法，而是「权限能不能隔离、任务会不会丢、表结构改错能不能回滚、
> 出了事查不查得到」。本版全部围绕这四件事。

### ✨ 新增

**知识库级 ACL（`kb_permissions`）**
- 用户 ↔ 知识库的读/写授权；管理员不受限
- **检索前过滤**：无权限的内容从未进入查询范围，不会出现在检索日志、LLM 上下文里
- 未授权的知识库在列表中不可见（不泄露「存在但无权访问」的库）
- 前端新增「授权管理」弹窗；无可用知识库时对话页给出明确提示

**审计日志（`audit_logs`）**
- 记录「谁 / 何时 / 对哪个对象 / 做了什么 / 来源 IP / 请求链路 ID」
- 覆盖：登录、登录失败、登录被锁定、注册、文档上传/删除/重建索引、知识库创建/删除、授权变更
- 新增 `GET /api/admin/audit-logs` 查询接口 + 管理端「审计日志」页面
- 写入失败不影响主业务（审计是附加证据，不是业务前置条件）

**任务队列（Celery + Redis）**
- 取代原先的 `threading.Thread(daemon=True)`
- `acks_late` + `task_reject_on_worker_lost`：worker 崩溃时任务退回队列而非消失
- 指数退避重试（30s / 60s / 120s，上限 600s），重试耗尽才标记失败
- 软/硬超时防止大文件永久占住 worker
- **启动对账**：把卡在「排队中/处理中」超过阈值的文档重新入队
- **降级机制**：Redis 不可用时降级为本地线程并打印醒目告警（绝不静默降级）

**数据库迁移（Alembic）**
- 取代原先手写的 `_migrate_add_kb_id` / `_migrate_add_feedback_columns`
- 两个版本：`0001_baseline`（历史基线）+ `0002_enterprise_hardening`（本版变更）
- 已用 `alembic check` 验证：**迁移产出的表结构与模型定义完全一致**
- 已验证 upgrade / downgrade / 再 upgrade 全链路可用

**接口限流与登录锁定**
- 登录 10/分钟、注册 5/小时、问答 30/分钟、上传 60/小时（均可配置）
- 同一账号连续失败 5 次锁定 15 分钟
- Redis 计数（多 worker 共享配额）；Redis 不可用时降级为进程内计数

**可观测性**
- `request_id` 贯穿一次请求的所有日志（复用上游 `X-Request-ID`，并回传给客户端）
- `LOG_FORMAT=json` 输出单行 JSON，可对接 ELK / Loki
- 新增 `/api/health/ready` 就绪探针：逐项探测 MySQL / Chroma / 上传目录

**上传安全**
- **文件头（魔数）校验**：`.pdf` 必须是 `%PDF`，`.docx`/`.epub` 必须是 ZIP 容器，`.mobi` 必须含 `BOOKMOBI` 标识
- 文件名净化：取 basename，剥离 `../`、反斜杠、Windows 保留字符
- 分块落盘边写边判大小（原先一次性读进内存再判，超大请求可打挂服务）

### 🚀 优化

| 优化项 | 优化前 | 优化后 | 说明 |
|--------|--------|--------|------|
| 前端 API 地址 | 3 处硬编码 `localhost:8000` | 统一走 `config.ts` + 构建时注入 | 换环境无需改代码 |
| 前端容器 API 地址 | 用 `environment` 设置（**对 Vite 无效**） | 改为 `build args` | Vite 环境变量是构建时替换的 |
| nginx SSE 代理 | 默认开启缓冲（流式变一次性） | `proxy_buffering off` | 否则「流式输出」形同虚设 |
| 文档处理可靠性 | 裸 daemon 线程，重启即丢 | Celery 持久化 + 重试 + 对账 | 见修复 1 |
| 文档状态粒度 | 只有 `processing` | 增加 `queued` | 可区分「没 worker」与「处理太慢」 |
| 数据库结构变更 | 手写 ALTER，不可回滚 | Alembic 版本化迁移 | 见修复 5 |
| 异常返回内容 | 含 `str(exc)` | 只回 request_id | 见修复 3 |

### 🐛 修复

**1. Redis 不可用时任务静默降级**
- **现象**：生产环境 Redis 挂掉后，上传文档表面正常，但进程一重启任务全部消失
- **根因**：降级逻辑如果没有告警，就是「看起来在工作，实际在丢数据」
- **影响**：每次发版丢失所有未处理的文档入库任务，且无人察觉
- **修复**：降级时打印 ERROR 级告警（含恢复步骤），并在上传响应中返回 `queue_mode` 字段

**2. 权限绕过：空集合被当成「检索全部」**
- **现象**：用户无任何知识库授权时，本应什么都查不到，实际却检索了全部知识库
- **根因**：`names = collection_names or list_collection_names()` —— 空列表 `[]` 是 falsy，
  被当成「未指定」而回退为「检索全部」。权限过滤恰好会产出空列表，于是**过滤反而变成了放行**
- **影响**：**未授权用户能读到全部知识库内容**，且内容会进入检索日志与 LLM 上下文
- **修复**：三处一律改用 `is None` 判断，明确区分「未指定（检索全部）」与「指定为空（什么都不查）」

**3. 全局异常泄露内部信息**
- **现象**：接口报 500 时，响应体里带着完整异常文本
- **根因**：`content={"detail": ..., "message": str(exc)}` 直接回显异常
- **影响**：SQLAlchemy / pymysql 的报错通常包含完整 SQL、表名、字段名；
  连接失败时甚至包含主机、端口、用户名 —— 等于把数据库结构送给任何能触发 500 的人
- **修复**：响应只回通用提示 + `request_id`，详细信息只进服务端日志

**4. `JWT_SECRET` 使用公开的占位值**
- **现象**：本机 `.env` 中 `JWT_SECRET` 就是代码里的默认占位字符串
- **根因**：配置项写了兜底默认值，而部署时没人改
- **影响**：**任何人可用这个公开值自行签发 `{"sub":"1","role":"admin"}` 冒充管理员** ——
  这不是「弱口令」，是后门
- **修复**：移除兜底值；生产环境未配置或仍是占位值则拒绝启动；开发环境自动生成随机密钥并告警。
  已为本机生成 64 字符随机密钥（**重启后需重新登录**）

**5. 表结构变更无版本、不可回滚**
- **现象**：需要改字段类型或加索引时无从下手，只能人工连数据库执行 SQL
- **根因**：只有 `Base.metadata.create_all`（只建新表）加两个手写的「加列」函数
- **影响**：没有任何变更记录，改错了无法回滚，多环境之间结构可能悄悄不一致
- **修复**：引入 Alembic。既有数据库自动识别并标记为基线，新的迁移增量执行

**6. 上传文件名未净化**
- **现象**：文件名直接拼进磁盘路径
- **根因**：`f"{uuid}_{file.filename}"` 只是加了前缀，`../` 完整保留在路径里
- **影响**：设计缺陷成立；但**当前不可直接利用** —— uuid 前缀那一段目录不存在，写入会先失败。
  属「应加固的隐患」而非「可被利用的漏洞」，如实记录
- **修复**：取 basename + 剥离危险字符（已验证 5 类穿越文件名全部被净化）

**7. 上传大小限制可被绕过**
- **现象**：20MB 限制在读完整个文件之后才判断
- **根因**：`await file.read()` 先把全部内容读进内存，再比较大小
- **影响**：客户端发一个超大请求就能耗尽服务内存
- **修复**：改为分块读取、边写边判，超限立即中断并删除半截文件

**8. 前端 Docker 部署的两个失效配置**
- **现象**：容器部署后前端仍请求 `localhost:8000`
- **根因**：① `api.ts` 硬编码地址，`VITE_API_BASE_URL` 从未被读取；
  ② 即便读取了，Vite 的环境变量是**构建时**替换的，在 compose 的 `environment` 里设置无效
- **修复**：抽出 `config.ts` 统一读取，Dockerfile 改用 `ARG` 传入，compose 用 `build.args`

### 🏗️ 工程

- **新增 `/save` skill**：把「更新改动详情 → 提交 → 写规范 commit message → 推送 → 打版本标签」
  固化为可复用流程。固化了本项目踩坑得出的约束：必须用 SSH（HTTPS 被网络阻断）、
  不把令牌粘贴进对话、提交前检查 `.env`、工作区干净时不造空提交
- **新增 `CHANGELOG.md`（本文件）**：要求每次保存版本时同步更新
- **docker-compose 修正**：
  - 移除 **不存在的 `./init-database.sql` 挂载**（MySQL 初始化静默跳过，新人部署必踩）
  - 移除**死配置** `chroma` 服务（后端用的是嵌入式 `PersistentClient`，从未连接过它，
    却白占 8000 端口、逼得 backend 改用 8001）
  - 新增 redis + worker 服务；backend 端口回归 8000
  - 各服务补 healthcheck，`depends_on` 改为按健康状态等待
- **依赖新增**：`alembic`、`celery`、`redis`
- **配置模板**：`.env.example` 补齐全部新增项并加注释
- **README 修正**：Embedding 模型由 `bge-large-zh-v1.5` 改为与实现一致的 `bge-small-zh-v1.5`；
  新增生产部署检查清单

### ✅ 本版验证记录

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 迁移与模型一致性 | `alembic check` | No new upgrade operations detected |
| 迁移可回滚 | `downgrade 0001` → `upgrade head` → `check` | 通过 |
| 权限隔离（授权前） | 新用户检索 | 可见 0 个知识库 / 0 条来源 |
| 权限隔离（授权后） | 授予 read 后检索 | 可见 1 个知识库 / 5 条来源 |
| 伪装文件拦截 | `.zip`→`.pdf`、`.exe`→`.pdf` | 均被拒绝 |
| 路径穿越 | 5 类穿越文件名 | 全部净化为 basename，uploads 外无文件产生 |
| 账号锁定 | 不同 IP 连错 6 次 | 第 6 次返回 429 |
| 接口限流 | 同 IP 高频登录 | 触发 429 |
| 审计链路 | 查询 `/api/admin/audit-logs` | 记录含操作人、目标、IP、request_id |
| 权限校验 | 普通用户访问审计接口 | 403 |
| 前端构建 | `tsc -b` + `npm run build` | 均通过 |
| **Docker 部署** | | |
| 容器健康 | `docker compose ps` | 5 个容器全部 `healthy`（含 worker 的 Celery ping 检查） |
| 就绪探针 | `/api/health/ready` | `mysql/chroma/upload_dir` 全 ok，`env=production` |
| 登录 | `POST /api/auth/login` | HTTP 200 |
| 审计链路 | `/api/admin/audit-logs` | 登录被正确记录 |
| **任务队列（容器内）** | 上传文档 | `queue_mode=celery`，worker 日志确认处理 |
| 状态流转（容器内） | 轮询文档状态 | `queued → processing → ready`（5 分块，4 秒） |
| 检索与生成（容器内） | 上传后提问 | 1 条来源，回答完全来自刚上传的文档，无编造 |
| Ollama 推理（容器内） | `/api/generate` | 中文回答正常 |
| 构建优化 | 上下文体积 | **1.01 GB → 908 B**（`.dockerignore`） |
| 构建优化 | torch 体积 | **2 GB+ → 196 MB**（CPU 版） |

### ⚠️ 已知局限

**Docker 部署中的两处临时变通（需在网络恢复后回归）**
- **Redis 用的是宿主机实例，不是容器**：镜像加速站 daocloud 的 CDN 主机
  `image-mirror.r2.daocloud.vip` 在部署期间完全不可达（两个 IP 均返回 HTTP 000），
  而测试的 8 个其它公共镜像站全部被阻断，`redis:7-alpine` 始终拉不下来。
  临时改用 `docker-compose.workarounds.yml` 把 backend/worker 指向宿主机的 Redis。
  **网络恢复后执行 `docker compose up -d`（不带 `-f`）即可回归纯容器部署**
- **backend 镜像是在旧镜像上加补丁层构建的**：`download.pytorch.org` 在部署中途
  也被阻断（SSL `UNEXPECTED_EOF`），无法完整重建。缺的只有 `beautifulsoup4`
  （只依赖可用的 PyPI 镜像），因此在其上补了一层。
  **网络恢复后执行 `docker compose build backend` 即得到正常镜像**
- 遗留标签 `rag-backend:base` 是补丁的基础层，确认重建成功后可删除
- 另外还有一处环境限制：`registry.ollama.ai` 被阻断，`qwen2.5:7b` 无法在容器内拉取，
  实现方式是**把宿主机已有的 4.4GB 模型文件直接复制进容器**

**其它未实测部分**
- Celery 的失败重试与启动对账逻辑**未做故障注入测试**：
  已验证正常路径（broker 投递 → worker 消费 → 完成），
  但「worker 崩溃后任务是否真的被重投」「卡住的文档能否被对账捞回」没有实测

**历史遗留（未解决）**
- **拒答阈值失效**：可回答问题（0.4354~0.7023）与拒答问题（0.3723~0.7045）的相似度完全重叠，
  单一阈值无法区分。正解是引入 cross-encoder Reranker（本环境 HuggingFace 被阻断）。
  当前拒答仍依赖 System Prompt 约束，实测有效
- 缓存为进程内状态，多 worker / 水平扩容后不一致
- PDF 无 OCR 与表格解析，扫描件会解析失败（现已给出明确原因而非笼统的 error）
- 无 Token 计量与成本统计
- 无多租户（`tenant_id`）隔离，当前只有「用户 ↔ 知识库」一层
- 前端 `ConversationList` 全量渲染且会话列表接口不分页，会话上千条会卡顿
- 无 React ErrorBoundary，任一组件抛错会整页白屏

---

## [v1.0.0] - 2026-09-10

企业级 RAG 能力里程碑：补齐**评估体系、检索质量、可观测性、反馈闭环**四块短板。

### ✨ 新增

**多知识库隔离**
- 新增 `knowledge_bases` 表，每个知识库绑定独立的 ChromaDB collection
- `documents.kb_id` 建立文档归属；上传/列表接口支持 `kb_id` 参数
- 检索支持指定单库或跨库归并（按 RRF 分数排序）
- 新增知识库 CRUD API；前端文档管理页与对话页均增加知识库选择器
- 启动时自动迁移：补 `kb_id` 列 + 创建默认知识库 + 归置历史文档

**混合检索**
- 向量（语义泛化）+ BM25（精确匹配）双路召回，RRF 倒数排序融合
- 候选去冗余（Jaccard 词集合相似度），避免重复内容挤占 Top-K 名额
- 无需训练、无需外部模型，纯本地实现

**评估体系（`eval/`）**
- 30 条黄金测试集，覆盖 fact / keyword / multihop / **refusal（拒答）** 四类场景
- 指标：Hit@K、Recall@K、MRR、拒答正确率
- 支持「向量-only vs 混合检索」对照实验，一键输出对比结论

**可观测性**
- 新增 `retrieval_logs` 表：记录每次检索的双路候选集、融合数量、去冗余数量、最终入选 chunk、耗时
- 新增 `GET /api/knowledge/retrieval-stats`：统计两路召回各自的贡献占比

**用户反馈闭环**
- `messages` 表新增 `feedback / feedback_reason / feedback_comment / feedback_at / retrieval_log_id`
- 新增 `POST /api/chat/messages/{id}/feedback`（点赞/点踩 + 原因标签）
- 新增 `GET /api/knowledge/bad-cases`：bad case 归档，每条**附带当次检索明细**
- 前端：答案下方 👍/👎 按钮，点踩时弹出原因标签（不准确/不完整/过时/无关）

**文档格式**
- 新增 EPUB 解析器（基于 `ebooklib`，逐章节提取）
- 新增 MOBI 解析器（先转 epub/html 再提取）
- 二者均为自研实现——LangChain 生态无官方 Loader

**可配置化**
- System Prompt 提取为 `RAG_SYSTEM_PROMPT` 环境变量，可按业务场景切换
- 新增混合检索相关配置项（候选数、RRF 常数、去冗余阈值等）

### 🚀 优化

| 优化项 | 优化前 | 优化后 | 说明 |
|--------|--------|--------|------|
| **中文 BM25 分词** | 单字切分 | **二元组（bigram）** | 单字会让「的/了/是」到处命中，噪声淹没真实信号 |
| **keyword 类查询 MRR** | 0.783 | **0.917** | 错误码/型号类查询的排序质量显著提升 |
| **平均检索耗时** | 182ms | **34ms** | BM25 索引按集合缓存 + 语料变更时失效 |
| **并发能力** | 检索阻塞事件循环 | 线程池异步执行 | `asyncio.to_thread` 包裹 |
| **配置健壮性** | 路径依赖启动目录 | 以 backend 为锚点 | 消除「静默连到空数据目录」 |
| **检索质量可度量** | 无 | Hit@5 83.3% / MRR 0.758 | 从「凭感觉调」变为「有数据可依」 |

### 🐛 修复

**1. 检索缓存不失效（用户可见）**
- **现象**：删除或重新索引文档后，最长 5 分钟内仍返回**引用已删除文档**的答案
- **根因**：`utils/cache.py` 暴露了 `cache_clear`，但 `process_document` /
  `delete_document_from_chroma` / `reindex_document` 三处均未调用
- **修复**：引入**失效回调注册机制**，语料变更时检索缓存与 BM25 索引同步失效

**2. 阻塞事件循环（并发瓶颈）**
- **现象**：并发提问时请求被迫排队
- **根因**：`async def` 接口内直接调用 `embedding_model.embed_query()`——这是同步阻塞的 CPU/GPU 操作
- **修复**：改用 `asyncio.to_thread`（注意不把 db session 传入线程，SQLAlchemy Session 非线程安全）

**3. `.docx` 上传静默失败**
- **现象**：上传后文档状态一直为 `error`
- **根因**：`Docx2txtLoader` 依赖 `docx2txt` 包，但 `requirements.txt` 只声明了 `python-docx`
  （**读/写是两个不同的包**）
- **修复**：补装并固化到依赖声明；重新索引验证通过

**4. 知识库原文含花括号导致问答 500**
- **现象**：检索到含 JSON 示例的文档时，接口报
  `Input to ChatPromptTemplate is missing variables {'task_id'}`
- **根因**：拼好的 Prompt 被交给 `ChatPromptTemplate` **二次解析**，
  文档里的 `{"task_id": ...}` 被当成模板变量
- **影响**：**知识库内容本身决定代码会不会崩**，属典型的数据驱动偶发故障
- **修复**：改为直接构造 `SystemMessage` / `HumanMessage` 对象，绕开模板解析

**5. 拒答后编造联系方式（幻觉）**
- **现象**：回答「知识库未收录」之后，又虚构了邮箱与电话
- **根因**：Prompt 只说了「不要编造」，未明确禁止编造联系方式类具体信息
- **修复**：强化约束，明确列出禁止编造的字段类型；修复后改为引用知识库中真实的支持渠道

**6. 配置相对路径依赖工作目录（隐蔽）**
- **现象**：从非 `backend/` 目录启动时，**静默连到一个空的数据目录**，
  表现为「知识库明明有数据却检索不到」，且不报任何错
- **根因**：`CHROMA_PERSIST_DIR=./chroma_data` 按**工作目录**解析
- **修复**：配置以 `backend/` 为锚点解析，任意目录启动都读到同一份数据
- **发现方式**：在 `eval/` 目录跑评估脚本时检索全部返回空，顺藤摸瓜定位

**7. 数据库表结构迁移缺失**
- **现象**：新增字段后接口报 500
- **根因**：`Base.metadata.create_all` **只建新表，不会修改已存在的表结构**
- **修复**：显式迁移（`documents.kb_id`、`messages` 五个反馈字段）

### 🏗️ 工程

- **删除 2 个危险调试脚本**：`test_rag.py` / `test_ingest.py` 开头即 `db.query(Document).delete()`，
  运行一次会**清空整个知识库**，且零断言（不是真正的测试）
- **清理招聘场景遗留**：删除 4 个零引用模型（`job_posting` / `job_application` / `resume` / `seeker_profile`）
  及对应的 4 张空表
- **依赖补全**：`docx2txt`、`ebooklib`、`mobi`、`rank-bm25`
- **安全**：`.env`（含 MySQL 密码、JWT 密钥）排除出版本库，改为提供 `.env.example` 模板
- **新增 `/run` skill**：一键启动后端+前端并跑端到端冒烟测试

### ⚠️ 已知局限

**拒答阈值失效——且无法用单一阈值解决**
- 实测两类问题的 Top1 相似度**完全重叠**：

  | 类别 | Top1 相似度范围 |
  |------|----------------|
  | 可回答问题 | 0.4354 ~ 0.7023 |
  | 拒答问题 | 0.3723 ~ **0.7045** |

- **原因**：bi-encoder 的余弦相似度衡量的是「语义大致相近」，
  对「主题相关但无答案」的问题天然给出较高分
- **当前表现**：检索层阈值过滤失效，但**生成层的拒答有效**
  （System Prompt 要求无信息时诚实说明），阈值仅作粗过滤
- **改进方向**：引入 Cross-encoder Reranker / LLM 相关性判定
  （本环境 HuggingFace 被网络阻断，无法下载模型）

**其他待解决**
- 缓存为进程内状态，多 worker / 水平扩容后不一致
- 文档入库使用裸 daemon 线程，无队列/重试/幂等，进程重启任务丢失
- PDF 解析无 OCR 与表格处理，扫描件会解析为空
- 无文档级 ACL（能访问某知识库即可检索其全部文档）
- 无 token 计量与成本统计

---

## [v0.1.0] - 2026-09-10

### ✨ 新增
- 初始版本：FastAPI 后端 + React 前端 + ChromaDB + MySQL + Ollama(qwen2.5:7b)
- JWT 认证，admin / 普通用户角色分离
- 中文优化的递归分块（chunk_size=500, overlap=50）
- SSE 流式输出、引用来源标注、多轮对话
- 相关度阈值过滤
- 支持 pdf / txt / md / csv / docx 上传
- 进程内 LRU + TTL 检索缓存
- Docker 部署配置
