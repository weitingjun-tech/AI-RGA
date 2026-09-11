# 构建阶段
#
# Node 版本必须 >=22.12（或 >=20.19）。
# 原因：项目用的是 Vite 8，其底层打包器 rolldown 依赖 `node:util` 的
# `styleText` 导出，这个 API 是 Node 20.12 才加入的。
# 用 node:18 会在 `npm run build` 阶段直接报
#   SyntaxError: The requested module 'node:util' does not provide an export named 'styleText'
# 本地开发机是 Node 24 所以不会暴露这个问题，只在容器里出现。
FROM node:22-alpine AS build

# 设置工作目录
WORKDIR /app

# 复制 package.json 和 package-lock.json
COPY package*.json ./

# 安装依赖
RUN npm ci

# 复制源代码
COPY . .

# 后端 API 地址。Vite 在 `vite build` 时就把这个值编译进产物，
# 所以必须作为**构建参数**传入 —— 在 docker-compose 的 environment 里设是无效的。
# 构建时指定：docker build --build-arg VITE_API_BASE_URL=https://api.example.com .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# 构建应用
RUN npm run build

# 生产阶段
FROM nginx:alpine

# 复制构建产物
COPY --from=build /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/nginx.conf

# 暴露端口
EXPOSE 5173

# 健康检查必须用 127.0.0.1 而不是 localhost：
# 容器内 /etc/hosts 把 localhost 解析到 IPv6 的 ::1，而 nginx 只监听 IPv4，
# 于是 wget 连 ::1 被拒，容器长期显示 unhealthy（实际服务是好的）。
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:5173/ >/dev/null || exit 1

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]