// RAG 知识库问答系统 - 问答主页面（现代企业级 UI）
import { useEffect, useRef, useState } from 'react';
import { Button, Select, Tooltip } from 'antd';
import {
  SendOutlined,
  PlusOutlined,
  MenuOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import { useChatStore } from '../store/chatStore';
import { useAuthStore } from '../store/authStore';
import { ConversationList } from '../components/ConversationList';
import { ChatMessage } from '../components/ChatMessage';
import { UserMenu } from '../components/UserMenu';
import { useNavigate } from 'react-router-dom';
import { DatabaseOutlined } from '@ant-design/icons';
import { knowledgeApi } from '../services/api';
import type { KnowledgeBase } from '../types';


const SUGGESTIONS = [
  '同步任务报 CONN_TIMEOUT 怎么排查？',
  '专业版包含多少同步额度？超额怎么收费？',
  'MySQL 实时同步到 Snowflake 需要什么套餐？',
];

export default function Chat() {
  const {
    conversations, currentConversation, messages,
    streaming, streamingContent,
    loadConversations, selectConversation, createConversation,
    deleteConversation, renameConversation,
    sendMessage, loadOlder,
    selectedKbIds, setSelectedKbIds,
  } = useChatStore();

  const { user, fetchUser } = useAuthStore();
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [siderCollapsed, setSiderCollapsed] = useState(false);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const olderLoadingRef = useRef(false);

  useEffect(() => {
    fetchUser();
    loadConversations();
    // 加载知识库列表，供检索范围选择
    knowledgeApi.getBases()
      .then((res) => setBases(res.data.bases || []))
      .catch(() => { /* 忽略：未登录或无权限时不展示选择器 */ });
  }, []);

  // 自动滚到底部
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingContent]);

  const handleSend = (query?: string) => {
    const q = (query ?? input).trim();
    if (!q || streaming) return;
    setInput('');

    if (!currentConversation) {
      createConversation().then((conv) => {
        if (conv) {
          // 等 store 更新后发送
          setTimeout(() => sendMessage(q), 100);
        }
      });
    } else {
      sendMessage(q);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 滚动到顶部时加载更早的历史消息
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollTop < 50 && !olderLoadingRef.current) {
      olderLoadingRef.current = true;
      loadOlder().finally(() => { olderLoadingRef.current = false; });
    }
  };

  return (
    <div className="chat-shell">
      {/* 侧栏 */}
      <aside className={`chat-sidebar ${siderCollapsed ? 'chat-sidebar--collapsed' : ''}`}>
        <ConversationList
          conversations={conversations}
          currentId={currentConversation?.id || null}
          loading={false}
          onSelect={selectConversation}
          onCreate={createConversation}
          onDelete={deleteConversation}
          onRename={renameConversation}
        />
      </aside>

      {/* 主区域 */}
      <main className="chat-main">
        {/* 头部 */}
        <header className="chat-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button
              type="text"
              icon={<MenuOutlined />}
              onClick={() => setSiderCollapsed(!siderCollapsed)}
              style={{ fontSize: 16 }}
            />
            <div className="brand-logo brand-logo--sm">
              <ThunderboltFilled />
            </div>
            <span className="brand-title">知识库问答系统</span>
            <span
              style={{
                fontSize: 12,
                color: '#64748b',
                background: '#eef2ff',
                padding: '2px 10px',
                borderRadius: 999,
                fontWeight: 600,
              }}
            >
              RAG
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {bases.length > 0 && (
              <Tooltip title="限定检索范围：不选则检索全部知识库">
                <Select
                  mode="multiple"
                  allowClear
                  maxTagCount="responsive"
                  style={{ minWidth: 220, maxWidth: 380 }}
                  placeholder="检索范围：全部知识库"
                  value={selectedKbIds}
                  onChange={setSelectedKbIds}
                  options={bases.map((b) => ({
                    value: b.id,
                    label: b.name,
                  }))}
                />
              </Tooltip>
            )}
            {user?.role === 'admin' && (
              <Button
                icon={<DatabaseOutlined />}
                onClick={() => navigate('/admin')}
                style={{
                  borderRadius: 10,
                  fontWeight: 600,
                  border: '1px solid #c7d2fe',
                  color: '#4f46e5',
                  background: '#eef2ff',
                }}
              >
                知识库管理
              </Button>
            )}
            <UserMenu />
          </div>
        </header>

        {/* 消息区域 */}
        <div
          className="chat-messages-container"
          ref={messagesContainerRef}
          onScroll={handleScroll}
        >
          {!currentConversation && !streaming ? (
            <div className="empty-state">
              <div className="empty-state-icon" style={{ width: 92, height: 92, borderRadius: 26, fontSize: 42 }}>
                <ThunderboltFilled />
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#1e293b' }}>
                知识库智能问答
              </div>
              <div style={{ fontSize: 14, color: '#64748b', textAlign: 'center' }}>
                基于检索增强生成，精准回答知识库中的问题
              </div>
              <div className="empty-suggestions">
                {SUGGESTIONS.map((s) => (
                  <div
                    key={s}
                    className="suggest-chip"
                    onClick={() => handleSend(s)}
                  >
                    {s}
                  </div>
                ))}
              </div>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => createConversation()}
                className="btn-brand"
                style={{ marginTop: 8, borderRadius: 10 }}
              >
                新建会话
              </Button>
            </div>
          ) : (
            <div style={{ maxWidth: 860, margin: '0 auto', padding: '28px 24px' }}>
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              {streaming && (
                <ChatMessage
                  message={{
                    id: -1,
                    conversation_id: currentConversation?.id || 0,
                    role: 'assistant',
                    content: streamingContent || '',
                    created_at: new Date().toISOString(),
                  }}
                  streaming
                />
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div className="chat-input-area">
          <div className="chat-input-box">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入您的问题... (Enter 发送，Shift+Enter 换行)"
              disabled={streaming}
              rows={1}
              style={{
                flex: 1,
                border: 'none',
                outline: 'none',
                background: 'transparent',
                fontSize: 14.5,
                lineHeight: 1.6,
                resize: 'none',
                padding: '8px 0',
                fontFamily: 'inherit',
              }}
              onInput={(e) => {
                const el = e.target as HTMLTextAreaElement;
                el.style.height = 'auto';
                el.style.height = Math.min(el.scrollHeight, 160) + 'px';
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={streaming}
              disabled={!input.trim() || streaming}
              onClick={() => handleSend()}
              className="btn-brand send-btn"
            />
          </div>
          <div
            style={{
              maxWidth: 860,
              margin: '8px auto 0',
              fontSize: 12,
              color: '#94a3b8',
              textAlign: 'center',
            }}
          >
            AI 生成内容仅供参考，请以知识库原始文档为准
          </div>
        </div>
      </main>
    </div>
  );
}