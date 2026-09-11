// RAG 知识库问答系统 - 聊天状态管理
import { create } from 'zustand';
import { chatApi } from '../services/api';
import { API_BASE_URL } from '../config';
import type { Conversation, Message, SourceCitation } from '../types';

interface ChatState {
  conversations: Conversation[];
  currentConversation: Conversation | null;
  messages: Message[];
  streaming: boolean;
  streamingContent: string;
  // 消息分页状态
  page: number;
  hasMore: boolean;
  // 检索范围：选中的知识库 ID（空数组 = 检索全部知识库）
  selectedKbIds: number[];
  setSelectedKbIds: (ids: number[]) => void;

  loadConversations: () => Promise<void>;
  selectConversation: (conv: Conversation) => Promise<void>;
  loadOlder: () => Promise<void>;
  createConversation: () => Promise<Conversation | null>;
  deleteConversation: (id: number) => Promise<void>;
  renameConversation: (id: number, title: string) => Promise<void>;

  addMessage: (msg: Message) => void;
  setStreaming: (v: boolean) => void;
  appendStreamingContent: (chunk: string) => void;
  finishStreaming: (sources?: SourceCitation[], messageId?: number) => void;
  clearStreamingContent: () => void;

  // SSE 发送消息
  sendMessage: (query: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversation: null,
  messages: [],
  streaming: false,
  streamingContent: '',
  page: 1,
  hasMore: false,
  selectedKbIds: [],

  setSelectedKbIds: (ids) => set({ selectedKbIds: ids }),

  loadConversations: async () => {
    try {
      const res = await chatApi.getConversations();
      set({ conversations: res.data.conversations || [] });
    } catch { /* ignore */ }
  },

  selectConversation: async (conv) => {
    set({ currentConversation: conv, messages: [], streamingContent: '', page: 1, hasMore: true });
    try {
      const res = await chatApi.getMessages(conv.id, 1);
      const msgs = res.data.messages || [];
      set({
        messages: msgs,
        page: 1,
        hasMore: msgs.length < (res.data.total || 0),
      });
    } catch { /* ignore */ }
  },

  loadOlder: async () => {
    const { currentConversation, page, hasMore } = get();
    if (!currentConversation || !hasMore) return;
    const nextPage = page + 1;
    try {
      const res = await chatApi.getMessages(currentConversation.id, nextPage);
      const older = res.data.messages || [];
      if (older.length === 0) {
        set({ hasMore: false });
        return;
      }
      set((s) => ({
        messages: [...older, ...s.messages],
        page: nextPage,
        hasMore: older.length + s.messages.length < (res.data.total || 0),
      }));
    } catch { /* ignore */ }
  },

  createConversation: async () => {
    try {
      const res = await chatApi.createConversation();
      const conv: Conversation = res.data;
      set((s) => ({ conversations: [conv, ...s.conversations] }));
      await get().selectConversation(conv);
      return conv;
    } catch {
      return null;
    }
  },

  deleteConversation: async (id) => {
    try {
      await chatApi.deleteConversation(id);
      set((s) => {
        const conversations = s.conversations.filter((c) => c.id !== id);
        const currentConversation =
          s.currentConversation?.id === id ? null : s.currentConversation;
        const messages = s.currentConversation?.id === id ? [] : s.messages;
        return { conversations, currentConversation, messages };
      });
    } catch { /* ignore */ }
  },

  renameConversation: async (id, title) => {
    try {
      await chatApi.renameConversation(id, title);
      set((s) => ({
        conversations: s.conversations.map((c) =>
          c.id === id ? { ...c, title } : c
        ),
        currentConversation:
          s.currentConversation?.id === id
            ? { ...s.currentConversation, title }
            : s.currentConversation,
      }));
    } catch { /* ignore */ }
  },

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setStreaming: (v) => set({ streaming: v }),
  appendStreamingContent: (chunk) =>
    set((s) => ({ streamingContent: s.streamingContent + chunk })),
  finishStreaming: (sources, messageId) => {
    const { streamingContent, currentConversation, messages } = get();
    if (streamingContent) {
      const msg: Message = {
        // 优先使用后端落库后的真实 ID，反馈接口需要它；取不到时退回本地时间戳
        id: messageId ?? Date.now(),
        conversation_id: currentConversation?.id || 0,
        role: 'assistant',
        content: streamingContent,
        sources,
        feedback: null,
        created_at: new Date().toISOString(),
      };
      set({
        messages: [...messages, msg],
        streamingContent: '',
        streaming: false,
      });
    }
  },
  clearStreamingContent: () => set({ streamingContent: '', streaming: false }),

  sendMessage: async (query) => {
    const { currentConversation, messages, selectedKbIds } = get();
    if (!query.trim()) return;

    // 构建完整的 SSE URL
    const token = localStorage.getItem('access_token');
    const baseUrl = API_BASE_URL;

    const body = JSON.stringify({
      conversation_id: currentConversation?.id || undefined,
      query,
      // 限定检索范围到选中的知识库；为空则由后端检索全部知识库
      kb_ids: selectedKbIds.length ? selectedKbIds : undefined,
    });

    // 添加用户消息
    const userMsg: Message = {
      id: Date.now(),
      conversation_id: currentConversation?.id || 0,
      role: 'user',
      content: query,
      created_at: new Date().toISOString(),
    };
    set({ messages: [...messages, userMsg], streaming: true, streamingContent: '' });

    try {
      const response = await fetch(`${baseUrl}/api/chat/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'chunk') {
              get().appendStreamingContent(data.content);
            } else if (data.type === 'done') {
              get().finishStreaming(data.sources, data.message_id);
              // 更新会话列表，确保新会话也出现
              get().loadConversations();
            } else if (data.type === 'error') {
              get().clearStreamingContent();
              console.error('SSE error:', data.message);
            }
          }
        }
      }
    } catch (e) {
      console.error('Send message error:', e);
      get().clearStreamingContent();
    }
  },
}));