// RAG 知识库问答系统 - 认证状态管理
import { create } from 'zustand';
import { authApi } from '../services/api';
import type { User } from '../types';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  isAdmin: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('access_token'),
  refreshToken: localStorage.getItem('refresh_token'),
  user: null,
  loading: false,

  login: async (username, password) => {
    set({ loading: true });
    try {
      const res = await authApi.login(username, password);
      const { access_token, refresh_token } = res.data;
      localStorage.setItem('access_token', access_token);
      localStorage.setItem('refresh_token', refresh_token);
      set({ token: access_token, refreshToken: refresh_token });
      // 获取用户信息
      const me = await authApi.getMe();
      set({ user: me.data, loading: false });
    } catch (e) {
      set({ loading: false });
      throw e;
    }
  },

  register: async (username, password) => {
    set({ loading: true });
    try {
      const res = await authApi.register(username, password);
      const { access_token, refresh_token } = res.data;
      localStorage.setItem('access_token', access_token);
      localStorage.setItem('refresh_token', refresh_token);
      set({ token: access_token, refreshToken: refresh_token });
      const me = await authApi.getMe();
      set({ user: me.data, loading: false });
    } catch (e) {
      set({ loading: false });
      throw e;
    }
  },

  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    set({ token: null, refreshToken: null, user: null });
  },

  fetchUser: async () => {
    const { token } = get();
    if (!token) return;
    try {
      const me = await authApi.getMe();
      set({ user: me.data });
    } catch {
      get().logout();
    }
  },

  isAdmin: () => get().user?.role === 'admin',
}));