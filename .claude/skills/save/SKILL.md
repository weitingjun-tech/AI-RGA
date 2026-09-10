---
name: save
description: 保存当前版本到 Git 并推送到 GitHub — 更新 CHANGELOG 改动详情（含优化与纠错点）、提交所有改动、写清晰的 commit message、推送到远端，可选打版本标签
---

# /save — 保存版本并上传到 Git

把当前工作区的改动保存为一个 Git 提交并推送到 GitHub。

**默认行为**：提交所有改动 → 推到 `origin/master` → 报告结果。
**带参数**：`/save v1.2.0` 会额外打一个带说明的版本标签并推送。

---

## 本项目的 Git 配置（重要，先读）

| 项目 | 值 |
|------|-----|
| 仓库 | `git@github.com:weitingjun-tech/AI-RGA.git`（**SSH**） |
| 分支 | `master` |
| 认证方式 | SSH 密钥（`~/.ssh/id_ed25519`），无需令牌 |

> ⚠️ **不要改回 HTTPS**。本网络环境下 `github.com:443` 被阻断（`Recv failure: Connection was reset`），
> 但 **SSH 端口 22 可用**。HTTPS 推送会失败。

> ⚠️ **绝不要把 GitHub 令牌粘贴到对话里**。之前发生过一次 PAT 泄露。
> 用 SSH 就完全不需要令牌。

---

## 执行步骤

### 1. 检查仓库状态

```bash
cd d:/mydo
git status --short          # 有哪些改动
git log --oneline -3        # 最近提交，用于写 commit message
git status -sb | head -1    # 与远程的差异（ahead/behind）
```

**若工作区干净（`git status --short` 无输出）**：
- 先检查是否有未推送的提交（`git status -sb` 显示 `ahead`）
- 都没有 → 告诉用户「当前版本已是最新，无需保存」，**不要创建空提交**

### 2. 确认没有敏感文件被提交

```bash
git status --short | grep -E "\.env$" && echo "⚠️ .env 被暂存，需排除"
```

`.gitignore` 已排除：`backend/.env`、`venv/`、`node_modules/`、`uploads/`、
`chroma_data/`、`huggingface_cache/`、`*.log`、`.claude/settings*.json`。

**若发现 `backend/.env` 被暂存，立即 `git rm --cached backend/.env` 并加入 `.gitignore`。**

### 3. 暂存并查看完整变更

```bash
git add -A
git status --short
```

### 4. 更新 `CHANGELOG.md`（必做）

**每次保存版本都必须更新根目录的 `CHANGELOG.md`。** 这是本 skill 的核心要求：
改动详情要留在仓库里，而不是只留在 commit message 里。

#### 写什么

把本次改动按分类补进对应版本小节。**要写清「优化了什么、修了什么问题」，
不要只写「优化了 XX」这种没有信息量的条目。**

四个必填分类 + 一个诚实分类：

| 分类 | 写什么 | 要求 |
|------|--------|------|
| ✨ **新增** | 新功能 | 说明功能是什么、解决什么问题 |
| 🚀 **优化** | 性能/质量/体验改进 | **必须带量化对比**（优化前 → 优化后） |
| 🐛 **修复** | 纠正的缺陷 | **必须写三段：现象 / 根因 / 修复方式**，并说明影响面 |
| 🏗️ **工程** | 依赖、构建、工具链、清理 | |
| ⚠️ **已知局限** | 尚未解决的问题 | **如实记录**，含原因与改进方向 |

#### 怎么写

**🐛 修复**条目按此模板（缺一不可）：

```markdown
**N. <一句话描述问题>**
- **现象**：用户/系统看到的是什么
- **根因**：为什么会发生
- **影响**：会导致什么后果（用户可见？数据风险？）
- **修复**：怎么改的，改动位置
```

**🚀 优化**条目优先用表格，带前后对比数字：

```markdown
| 优化项 | 优化前 | 优化后 | 说明 |
|--------|--------|--------|------|
| 中文 BM25 分词 | 单字切分 | 二元组(bigram) | 单字会让「的/了/是」到处命中 |
```

> **没有量化数据时不要编造。** 写「优化了检索延迟」不如写
> 「检索延迟从 182ms 降至 34ms（评估脚本实测）」；如果没测过，就如实描述改了什么。

#### 版本小节怎么放

- **已打标签的版本** → 补进对应版本小节（如 `## [v1.0.0]`），**不要改历史**
- **未打标签的新改动** → 放进 `## [未发布]` 小节
- **本次要打新标签**（如 `/save v1.1.0`）→ 把 `[未发布]` 的内容
  移到新建的 `## [v1.1.0] - <日期>` 小节下

#### 同时更新版本链接（可选）

若文件底部有版本对比链接，新增版本时同步补一行。

---

### 5. 写提交信息

**不要用 `git commit -m "update"` 这种无信息量的消息。** 参照本仓库已有的风格：

```
<type>: <一句话概括>

<具体做了什么>
- 要点 1
- 要点 2

<可选：修复的问题 / 影响>
```

`<type>` 取值：`feat` / `fix` / `chore` / `docs` / `refactor` / `test`

**写消息前先看 diff**，理解改动内容再写：

```bash
git diff --cached --stat    # 改动概览
git diff --cached           # 详细改动（文件多时只看关键文件）
```

### 6. 提交并推送

```bash
git add CHANGELOG.md        # 确保改动日志一并提交
git commit -m "<写好的消息>"
git push
```

### 7. 可选：打版本标签

**仅当用户明确要求版本号时执行**（如 `/save v1.2.0`）。

```bash
git tag -a v1.2.0 -m "v1.2.0 — <本版本主要内容>

<要点列表>"
git push origin v1.2.0
```

版本号约定（语义化版本）：
- **主版本**：不兼容的重大变更
- **次版本**：新增功能
- **修订号**：Bug 修复

查看已有标签：`git tag -l -n1`

### 8. 报告结果

向用户报告：
- 提交哈希与消息
- 推送状态（是否成功、推到哪个分支）
- 若打了标签，报告标签名
- 本次改动的文件数与要点
- **CHANGELOG.md 中本次新增/修改的条目摘要**

---

## 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `Recv failure: Connection was reset` | 用了 HTTPS（此网络下 `github.com:443` 被阻断） | 改回 SSH：`git remote set-url origin git@github.com:weitingjun-tech/AI-RGA.git` |
| `Permission denied (publickey)` | SSH 公钥未添加到 GitHub | 生成密钥 `ssh-keygen -t ed25519`，把 `~/.ssh/id_ed25519.pub` 内容添加到 https://github.com/settings/ssh/new |
| `nothing to commit` | 没有实际改动 | 正常提示，不要造空提交 |
| 提交里混入了 `.env` | `.gitignore` 未生效或文件已被跟踪 | `git rm --cached backend/.env`，确认 `.gitignore` 含该规则 |
| 想撤销上一次提交但保留改动 | — | `git reset --soft HEAD~1` |

---

## 快速执行（改动明确时）

```bash
cd d:/mydo && git add -A && git status --short   # 先看改了什么
# 1. 根据 diff 更新 CHANGELOG.md（优化点带数字、修复点写现象/根因/修复）
# 2. 写 commit message
git add CHANGELOG.md && git commit -m "<消息>" && git push
```

**最容易被跳过的一步就是更新 `CHANGELOG.md`**——但它恰恰是这个 skill 存在的意义：
让每个版本的优化与纠错点沉淀在仓库里，而不是散落在 commit message 和对话记录中。
