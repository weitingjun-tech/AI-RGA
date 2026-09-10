// RAG 知识库问答系统 - 聊天消息组件（气泡式设计）
import { useState } from 'react';
import { Avatar, Button, Popover, Space, Tag, message as antdMessage } from 'antd';
import {
  UserOutlined, ThunderboltFilled,
  LikeOutlined, LikeFilled, DislikeOutlined, DislikeFilled,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { SourceCitation } from './SourceCitation';
import { chatApi } from '../services/api';
import type { Message } from '../types';

const DOWN_REASONS = ['不准确', '不完整', '内容过时', '与问题无关'];

export function ChatMessage({ message, streaming = false }: { message: Message; streaming?: boolean }) {
  const isUser = message.role === 'user';
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(message.feedback ?? null);
  const [popoverOpen, setPopoverOpen] = useState(false);

  const canFeedback = !isUser && !streaming && message.id > 0;

  const submit = async (type: 'up' | 'down', reason?: string) => {
    if (!canFeedback) return;
    setFeedback(type);
    setPopoverOpen(false);
    try {
      await chatApi.submitFeedback(message.id, type, reason);
      antdMessage.success(type === 'up' ? '感谢反馈' : '已记录，我们会据此改进');
    } catch {
      setFeedback(message.feedback ?? null);
      antdMessage.error('反馈提交失败');
    }
  };

  return (
    <div className="msg-row" style={{ flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <Avatar
        className="msg-avatar"
        icon={isUser ? <UserOutlined /> : <ThunderboltFilled />}
        style={{
          backgroundColor: isUser ? '#6366f1' : '#8b5cf6',
          width: 34,
          height: 34,
        }}
      />
      <div
        style={{
          maxWidth: '76%',
          padding: '12px 16px',
        }}
        className={isUser ? 'msg-bubble--user' : 'msg-bubble--assistant'}
      >
        {isUser ? (
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
            {message.content}
          </div>
        ) : (
          <div className={`markdown-content ${streaming ? 'streaming-cursor' : ''}`}>
            {streaming && !message.content ? (
              <span className="thinking-dots">
                <span /> <span /> <span />
              </span>
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            )}
            {!streaming && message.sources && message.sources.length > 0 && (
              <SourceCitation sources={message.sources} />
            )}
          </div>
        )}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 11,
            opacity: 0.55,
            marginTop: 6,
            justifyContent: isUser ? 'flex-end' : 'flex-start',
            color: isUser ? '#fff' : '#64748b',
          }}
        >
          <span>{new Date(message.created_at).toLocaleTimeString()}</span>

          {/* 用户反馈：没有反馈数据，所有质量优化都是拍脑袋 */}
          {canFeedback && (
            <Space size={2} style={{ marginLeft: 4 }}>
              <Button
                type="text"
                size="small"
                style={{ padding: '0 4px', height: 20, color: feedback === 'up' ? '#16a34a' : '#94a3b8' }}
                title="回答有帮助"
                onClick={() => submit('up')}
              >
                {feedback === 'up' ? <LikeFilled /> : <LikeOutlined />}
              </Button>
              <Popover
                open={popoverOpen}
                onOpenChange={(o) => canFeedback && setPopoverOpen(o)}
                trigger="click"
                content={
                  <div style={{ maxWidth: 220 }}>
                    <div style={{ marginBottom: 6, fontSize: 12 }}>请选择问题类型（帮助定位原因）</div>
                    <Space wrap size={4}>
                      {DOWN_REASONS.map((r) => (
                        <Tag
                          key={r}
                          style={{ cursor: 'pointer' }}
                          onClick={() => submit('down', r)}
                        >
                          {r}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                }
              >
                <Button
                  type="text"
                  size="small"
                  style={{ padding: '0 4px', height: 20, color: feedback === 'down' ? '#dc2626' : '#94a3b8' }}
                  title="回答没帮助"
                >
                  {feedback === 'down' ? <DislikeFilled /> : <DislikeOutlined />}
                </Button>
              </Popover>
            </Space>
          )}
        </div>
      </div>
    </div>
  );
}