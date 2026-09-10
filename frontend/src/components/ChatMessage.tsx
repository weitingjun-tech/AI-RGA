// RAG 知识库问答系统 - 聊天消息组件（气泡式设计）
import { Avatar } from 'antd';
import { UserOutlined, ThunderboltFilled } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { SourceCitation } from './SourceCitation';
import type { Message } from '../types';

export function ChatMessage({ message, streaming = false }: { message: Message; streaming?: boolean }) {
  const isUser = message.role === 'user';

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
            fontSize: 11,
            opacity: 0.55,
            marginTop: 6,
            textAlign: isUser ? 'right' : 'left',
            color: isUser ? '#fff' : '#64748b',
          }}
        >
          {new Date(message.created_at).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}