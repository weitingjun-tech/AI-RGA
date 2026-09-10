// RAG 知识库问答系统 - API 服务层
import axios, { AxiosError } from 'axios';
import type { InternalAxiosRequestConfig } from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

// 请求拦截器：自动携带 Token
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器：Token 过期自动刷新
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        try {
          const res = await axios.post('http://localhost:8000/api/auth/refresh', null, {
            params: { refresh_token: refreshToken },
          });
          localStorage.setItem('access_token', res.data.access_token);
          if (error.config?.headers) {
            error.config.headers.Authorization = `Bearer ${res.data.access_token}`;
          }
          return axios(error.config!);
        } catch {
          localStorage.clear();
          window.location.href = '/login';
        }
      } else {
        localStorage.clear();
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// ==================== 认证 API ====================
export const authApi = {
  login: (username: string, password: string) =>
    api.post('/api/auth/login', { username, password }),
  register: (username: string, password: string) =>
    api.post('/api/auth/register', { username, password }),
  getMe: () => api.get('/api/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    api.post('/api/auth/change-password', { old_password, new_password }),
};

// ==================== 问答 API ====================
export const chatApi = {
  getConversations: () => api.get('/api/chat/conversations'),
  createConversation: () => api.post('/api/chat/conversations'),
  deleteConversation: (id: number) => api.delete(`/api/chat/conversations/${id}`),
  renameConversation: (id: number, title: string) =>
    api.put(`/api/chat/conversations/${id}?title=${encodeURIComponent(title)}`),
  getMessages: (convId: number, page: number = 1) =>
    api.get(`/api/chat/conversations/${convId}/messages?page=${page}&page_size=20`),
  // 流式请求不经过 axios（直接 fetch + SSE）
};

// ==================== 知识库 API ====================
export const knowledgeApi = {
  getDocuments: (page: number = 1) =>
    api.get(`/api/knowledge/documents?page=${page}&page_size=20`),
  getDocumentStatus: (id: number) => api.get(`/api/knowledge/documents/${id}`),
  uploadDocument: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/api/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  deleteDocument: (id: number) => api.delete(`/api/knowledge/documents/${id}`),
  reindexDocument: (id: number) => api.post(`/api/knowledge/documents/${id}/reindex`),
  getStats: () => api.get('/api/knowledge/stats'),
  getUsers: () => api.get('/api/knowledge/users'),
  deleteUser: (id: number) => api.delete(`/api/knowledge/users/${id}`),
};

export default api;