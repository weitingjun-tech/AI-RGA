// RAG 知识库问答系统 - TypeScript 类型定义

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'user';
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  username: string;
  role: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

export interface Conversation {
  id: number;
  user_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SourceCitation {
  doc_id: number;
  doc_name: string;
  chunk_id: string;
  text_snippet: string;
  score: number;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceCitation[];
  created_at: string;
  /** 用户反馈：up=有帮助 down=没帮助 */
  feedback?: FeedbackType | null;
  feedback_reason?: string | null;
  feedback_comment?: string | null;
}

export interface ChatRequest {
  conversation_id?: number;
  query: string;
  /** 指定检索的知识库 ID 列表；为空表示检索全部知识库 */
  kb_ids?: number[];
}

export interface KnowledgeBase {
  id: number;
  name: string;
  description?: string | null;
  collection_name: string;
  is_default?: string | null;
  doc_count: number;
  chunk_count: number;
  created_at?: string;
}

export type FeedbackType = 'up' | 'down';

export interface Document {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: 'processing' | 'ready' | 'error';
  uploaded_by: number;
  kb_id?: number | null;
  created_at: string;
}

export interface SSEChunk {
  type: 'chunk' | 'done' | 'error';
  content?: string;
  conversation_id?: number;
  /** 助手消息落库后的真实 ID，前端据此提交反馈 */
  message_id?: number;
  sources?: SourceCitation[];
  message?: string;
}