# RAG 后端镜像
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 构建参数：源可切换。
# 默认值适用于能直连官方源的网络；国内环境用 compose 覆盖成镜像站。
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
# torch 版本必须锁：与 requirements.txt 里锁定的 transformers 4.46.3 /
# sentence-transformers 3.3.1 是配套的一组。不锁会装到最新版并引发依赖回溯。
ARG TORCH_VERSION=2.13.0

# 编译工具：部分依赖（如 mobi）没有预编译 wheel，需要现场编译
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ---------------------------------------------------------------------------
# 必须先单独装 CPU 版 torch —— 这一步能省掉 2GB 以上的下载量
#
# 为什么：PyPI 上的 Linux 版 torch 默认**捆绑 CUDA 运行时**（2GB+），
# 但本容器不挂 GPU，那些 CUDA 库纯属死重量。
# 从 pytorch 官方的 cpu 索引装，wheel 只有 200MB 左右。
#
# 注意顺序：torch 必须先装。反过来先装 requirements.txt 的话，
# pip 会从 PyPI 解析并下载 CUDA 版，之后不会再替换。
# ---------------------------------------------------------------------------
RUN pip install --no-cache-dir --index-url ${TORCH_INDEX_URL} torch==${TORCH_VERSION}

# 其余依赖。torch 已满足，pip 不会重复下载。
RUN pip install --no-cache-dir --index-url ${PIP_INDEX_URL} -r requirements.txt

COPY . .

# 以非 root 运行。容器被攻破时，root 权限可以直接映射到宿主机的挂载目录，
# 非 root 能把爆炸半径限制在应用目录内。
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/uploads /app/chroma_data /app/huggingface_cache \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 就绪探针由应用自身的 /api/health/ready 提供（会逐项探测 MySQL / Chroma / 上传目录）
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health/ready', timeout=5).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
