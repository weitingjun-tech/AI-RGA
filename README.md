# RAG 企业级知识库问答系统

基于 LangChain 框架开发的 RAG（检索增强生成）企业级知识库问答系统，面向电商平台商品知识库场景。系统实现了完整的用户管理、知识库管理、智能问答等功能，支持多种文档格式和流式输出。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python FastAPI |
| AI 框架 | LangChain + LangChain Community |
| LLM | 本地 Ollama (qwen2.5:7b) |
| Embedding | BAAI/bge-large-zh-v1.5 |
| 向量数据库 | ChromaDB |
| 关系数据库 | MySQL 8.0 |
| 前端框架 | React 18 + Vite + TypeScript |
| UI 组件库 | Ant Design 5 |

## 🌟 核心功能

### 📚 知识库管理
- **多格式支持**：PDF/TXT/MD/CSV/DOCX/**EPUB/MOBI** 文档上传（EPUB/MOBI 解析器为自研实现）
- **多知识库隔离**：每个知识库绑定独立的向量集合，检索时互不干扰，从根本上避免跨库语料污染
- **智能分块**：针对中文标点优化的递归分块，支持重叠
- **向量化存储**：使用 BGE 模型生成文档向量
- **批量处理**：支持批量上传和异步处理
- **状态监控**：实时显示文档处理状态

### 💬 RAG 智能问答
- **流式输出**：实时生成回答，提升用户体验
- **知识引用**：自动标注回答来源，提高可信度
- **多轮对话**：支持上下文连续对话
- **语义检索**：基于向量相似度精准匹配
- **相关度过滤**：自动过滤低相关度内容

### 👥 用户管理
- **注册登录**：支持用户注册、登录、密码修改
- **JWT 认证**：安全的令牌认证机制
- **权限控制**：admin 和普通用户权限分离
- **会话管理**：独立会话、历史持久化

### 🎨 用户体验
- **响应式设计**：适配桌面端和移动端
- **暗色模式**：支持系统主题跟随
- **Markdown 渲染**：富文本回答格式
- **实时反馈**：操作状态即时提示
- **优雅交互**：流畅的动画和过渡

## 🚀 快速启动

### 前置条件

1. **Python 3.11+** 已安装
2. **MySQL 8.0** 已运行，root 密码为 `root`
3. **Node.js 18+** 已安装
4. **Ollama** 已安装并拉取模型 `qwen2.5:7b`
   ```bash
   ollama pull qwen2.5:7b
   ```

### 系统架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React前端     │    │  FastAPI后端    │    │   外部服务      │
│                │    │                │    │                │
│ ┌─────────────┐ │    │ ┌─────────────┐ │    │ ┌─────────────┐ │
│ │  用户界面   │ │◄──►│ │   API网关    │ │◄──►│ │  MySQL 8.0  │ │
│ │  状态管理   │ │    │ │   JWT认证    │ │    │ │   ChromaDB   │ │
│ │  路由管理   │ │    │ │   RAG服务   │ │    │ │   Ollama     │ │
│ └─────────────┘ │    │ └─────────────┘ │    │ └─────────────┘ │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 启动步骤

```bash
# 1. 后端
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. 前端（新终端）
cd frontend
npm install
npm run dev
```

3. 打开浏览器访问 `http://localhost:5173`

### 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | 123456 |

管理员拥有知识库管理权限（上传/删除文档），普通用户仅可使用问答功能。

## 项目结构

```
mydo/
├── backend/                    # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py            # 应用入口
│   │   ├── config.py          # 配置管理
│   │   ├── database.py        # MySQL 连接池
│   │   ├── models/            # ORM 模型
│   │   │   ├── user.py
│   │   │   ├── conversation.py
│   │   │   ├── message.py
│   │   │   └── document.py
│   │   ├── schemas/           # Pydantic 数据模型
│   │   ├── api/               # 路由处理
│   │   │   ├── auth.py        # 认证接口
│   │   │   ├── chat.py        # 问答接口
│   │   │   └── knowledge.py   # 知识库管理接口
│   │   ├── services/          # 业务逻辑
│   │   │   ├── auth_service.py
│   │   │   ├── rag_service.py # RAG 核心流程
│   │   │   └── kb_service.py  # 文档处理
│   │   ├── middleware/        # JWT 中间件
│   │   └── utils/             # 缓存等工具
│   ├── chroma_data/           # 向量数据库存储
│   ├── uploads/               # 上传文档存储
│   ├── requirements.txt
│   └── .env
├── frontend/                   # React + Vite 前端
│   ├── src/
│   │   ├── pages/             # 页面组件
│   │   │   ├── Login.tsx
│   │   │   ├── Register.tsx
│   │   │   ├── Chat.tsx       # 问答主界面
│   │   │   └── admin/
│   │   │       ├── Dashboard.tsx
│   │   │       └── KbManage.tsx
│   │   ├── components/        # 通用组件
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── SourceCitation.tsx
│   │   │   ├── ConversationList.tsx
│   │   │   ├── UserMenu.tsx
│   │   │   └── ProtectedRoute.tsx
│   │   ├── services/api.ts    # HTTP 客户端
│   │   ├── store/             # Zustand 状态管理
│   │   └── types/             # TS 类型定义
│   └── package.json
└── README.md
```

## API 文档

启动后端后访问 `http://localhost:8000/docs` 查看 Swagger UI。

## 环境变量

后端配置通过 `.env` 文件管理，主要配置项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| MYSQL_PASSWORD | root | MySQL 密码 |
| OLLAMA_MODEL | qwen2.5:7b | Ollama 模型名 |
| EMBEDDING_MODEL | BAAI/bge-large-zh-v1.5 | Embedding 模型 |
| CHUNK_SIZE | 500 | 文本分块大小 |
| RETRIEVAL_TOP_K | 5 | 检索返回数量 |