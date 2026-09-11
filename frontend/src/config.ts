// 全局运行时配置
//
// API 地址通过 Vite 环境变量注入：开发时读 .env.development，
// 构建时由 Dockerfile 的 ARG 传入。
//
// 注意：Vite 的环境变量是**构建时**替换的（会被编译进产物），
// 不是运行时读取。所以改地址必须重新构建前端，改容器环境变量无效。

const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/** 后端 API 根地址，例如 http://localhost:8000 */
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '');
