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
}

export interface ChatRequest {
  conversation_id?: number;
  query: string;
}

export interface Document {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: 'processing' | 'ready' | 'error';
  uploaded_by: number;
  created_at: string;
}

export interface SSEChunk {
  type: 'chunk' | 'done' | 'error';
  content?: string;
  conversation_id?: number;
  sources?: SourceCitation[];
  message?: string;
}