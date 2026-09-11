# Docker 部署准备清单

> 本文档是**准备工作**,里面的命令**尚未执行**。
> 每一步都标注了「谁来执行」——标着「你」的步骤我无法代劳(需要管理员权限或重启)。

---

## 当前环境实测结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 操作系统 | Windows 11 家庭中文版 (10.0.22000) | **家庭版没有 Hyper-V**,Docker Desktop 只能走 WSL2 后端 |
| CPU 虚拟化 | ✅ BIOS 已开启 | `VirtualizationFirmwareEnabled: True` |
| 磁盘空间 | ✅ D 盘剩余 171 GB | C 盘仅剩 16 GB,所以 Docker 数据必须放 D 盘 |
| 网络 - Docker 官网 | ✅ 可达 | |
| 网络 - GitHub | ✅ 可达 | |
| **网络 - Docker Hub** | ❌ **不可达** | `registry-1.docker.io` 被墙,**必须配镜像加速** |
| 网络 - 镜像加速站 | ✅ 可达 | `docker.m.daocloud.io`、`registry.cn-hangzhou.aliyuncs.com` |
| WSL 应用 | ⚠️ 已安装 (2.7.13.0) | 但缺少虚拟机平台组件,无法启动 |
| VirtualMachinePlatform | ❌ 未启用 | 需要管理员 + 重启 |
| 管理员权限 | ❌ 当前会话不是管理员 | |
| Docker Desktop | ❌ 未安装 | |

**结论:Docker 能装,但需要你亲自完成两件事——提权和重启。之后的部分我可以接手。**

---

## 步骤 1:启用 WSL2 —— ⚠️ 需要你执行(管理员 + 重启)

以**管理员身份**打开 PowerShell(开始菜单搜索 PowerShell → 右键 → 以管理员身份运行),执行:

```powershell
wsl --install --no-distribution
```

`--no-distribution` 表示只装 WSL2 运行环境、不装 Ubuntu 等发行版
(Docker Desktop 会自己创建它需要的 `docker-desktop` 发行版)。

执行完**重启电脑**。

### 重启后验证

```powershell
wsl --status
```

期望看到:
- 默认版本: 2
- **不再出现**「WSL2 无法启动,因为未启用虚拟机平台」这类提示

如果仍提示缺少虚拟机平台,说明功能没启用成功,改用下面这条(仍需管理员 + 重启):

```powershell
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```

---

## 步骤 2:配置镜像加速 —— ⚠️ 需要你执行(必须在装 Docker 之前)

**为什么必须先做这一步**:Docker Hub 在本网络下不可达,不配镜像的话
`docker compose up` 会卡在 `docker pull mysql:8.0` 然后超时失败。

在 **`C:\Users\lizhi3\.docker\daemon.json`** 创建文件(目录不存在就新建),
内容如下:

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://registry.cn-hangzhou.aliyuncs.com"
  ],
  "data-root": "D:\\docker-data"
}
```

两个字段的作用:
- `registry-mirrors`:镜像加速站列表,Docker 会按顺序尝试
- `data-root`:**把镜像和容器数据放到 D 盘**。
  默认在 `C:\ProgramData\Docker`,而 C 盘只剩 16 GB——
  光 `ollama/ollama` + 构建 backend 镜像(要装 torch)就需要 5 GB 以上,
  放 C 盘一定撑爆

> 这个文件 Docker Desktop 首次启动后也能在
> Settings → Docker Engine 里改,但**先写好再启动更省事**。

---

## 步骤 3:安装 Docker Desktop —— ⚠️ 需要你执行

下载地址(约 600 MB):

```
https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe
```

安装时:
- ✅ 勾选 **Use WSL 2 instead of Hyper-V**(家庭版只能选这个)
- ✅ 勾选 **Add shortcut to desktop**

安装完成后启动 Docker Desktop,首次启动会问是否登录/跳过,选 **Skip** 即可。

### 启动后确认三件事

```powershell
docker --version
docker compose version
docker info --format "{{.DockerRootDir}}"     # 应显示 D:\docker-data
```

如果第三项显示的是 `C:\ProgramData\Docker`,说明 `daemon.json` 没生效,
到 Docker Desktop → Settings → Resources → **Disk image location** 手动改到 D 盘。

---

## 步骤 4:启动项目 —— ✅ 这步可以我来做

```bash
cd d:/mydo
cp backend/.env.example backend/.env
# 生成并填入 JWT_SECRET（必填，否则后端拒绝启动）
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d
```

首次启动会比较慢,原因:
1. 拉取基础镜像(mysql / redis / ollama / node / python,合计约 2 GB)
2. 构建 backend 镜像时安装 `sentence-transformers` + `torch`(**约 3-5 GB**)
3. 拉取 `qwen2.5:7b` 模型(约 4.7 GB)

`docker compose ps` 全部为 `healthy` 后,访问 `http://localhost:5173`。

---

## 预期会遇到的问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `docker pull` 卡住后超时 | 镜像加速没配或配错 | 检查 `daemon.json`;重启 Docker Desktop |
| `no space left on device` | 数据目录还在 C 盘 | 确认 `docker info` 的 DockerRootDir 是 D 盘 |
| backend 容器反复重启 | `JWT_SECRET` 没填,生产模式拒绝启动 | 检查 `docker compose logs backend` |
| backend 镜像构建失败在 pip | 网络问题 | 项目已配国内 pip 源则正常;否则需加 `-i` 参数 |
| compose 里 ollama 拉不动模型 | 容器内需要联网 | 进容器手动 `docker exec -it rag-ollama ollama pull qwen2.5:7b` |

---

## 如果你不想装 Docker

**Docker 不是必需的。** 它解决的是「一键部署给别人」的问题,
而本项目**现在已经可以用便携方式完整运行**:

- Redis:便携版已装在 `D:\tools\redis`,直接运行 `redis-server.exe redis-rag.conf`
- Celery worker / 后端 / 前端:直接跑各自的命令

Docker 的收益是「交付给客户时一条命令起全栈」和「环境一致性」。
如果近期目标是**面试演示**,本地跑完全够用,不必为此折腾重启。

建议的顺序:先确认面试需要展示什么。如果面试官可能问「你们怎么部署」,
那 Docker 值得装;只是自己演示的话优先级可以往后放。
