// RAG 知识库问答系统 - 会话列表侧栏（现代企业级样式）
import { useState } from 'react';
import { Button, Input, Modal, Typography, Popconfirm } from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  MessageOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import type { Conversation } from '../types';

const { Text } = Typography;

export function ConversationList({
  conversations,
  currentId,
  loading,
  onSelect,
  onCreate,
  onDelete,
  onRename,
}: {
  conversations: Conversation[];
  currentId: number | null;
  loading: boolean;
  onSelect: (conv: Conversation) => void;
  onCreate: () => void;
  onDelete: (id: number) => void;
  onRename: (id: number, title: string) => void;
}) {
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const openRename = (conv: Conversation) => {
    setRenameTarget(conv);
    setRenameValue(conv.title);
  };

  const confirmRename = () => {
    if (renameTarget && renameValue.trim()) {
      onRename(renameTarget.id, renameValue.trim());
    }
    setRenameTarget(null);
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', width: '100%' }}>
      {/* 品牌头 */}
      <div
        style={{
          padding: '18px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          borderBottom: '1px solid #eef2ff',
          background: 'linear-gradient(180deg, #eef2ff 0%, #f5f3ff 100%)',
        }}
      >
        <div className="brand-logo brand-logo--sm">
          <ThunderboltFilled />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span className="brand-title" style={{ fontSize: 15 }}>
            知识库问答
          </span>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>RAG 智能知识库</span>
        </div>
      </div>

      {/* 新建按钮 */}
      <div style={{ padding: '12px 14px' }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={onCreate}
          loading={loading}
          className="btn-brand"
          style={{ height: 38, borderRadius: 10 }}
        >
          新建会话
        </Button>
      </div>

      {/* 会话列表 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {conversations.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
            <MessageOutlined style={{ fontSize: 28, marginBottom: 10, display: 'block', opacity: 0.5 }} />
            暂无会话
            <br />
            点击上方「新建会话」开始提问
          </div>
        ) : (
          conversations.map((conv) => {
            const active = conv.id === currentId;
            return (
              <div
                key={conv.id}
                className={`conv-item ${active ? 'conv-item--active' : ''}`}
                onClick={() => onSelect(conv)}
                style={{ position: 'relative' }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    minWidth: 0,
                    paddingRight: active ? 52 : 0,
                  }}
                >
                  <MessageOutlined
                    style={{ color: active ? '#6366f1' : '#94a3b8', fontSize: 12, flexShrink: 0 }}
                  />
                  <Text
                    ellipsis
                    style={{
                      fontSize: 13,
                      color: active ? '#4f46e5' : '#334155',
                      fontWeight: active ? 600 : 400,
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    {conv.title}
                  </Text>
                </div>
                <div
                  className="conv-item-actions"
                  style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', display: 'flex' }}
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      openRename(conv);
                    }}
                  />
                  <Popconfirm
                    title="删除该会话？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      onDelete(conv.id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="删除"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 重命名弹窗 */}
      <Modal
        title="重命名会话"
        open={!!renameTarget}
        onOk={confirmRename}
        onCancel={() => setRenameTarget(null)}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ className: 'btn-brand' }}
        destroyOnClose
      >
        <Input
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onPressEnter={confirmRename}
          placeholder="输入新的会话标题"
          style={{ marginTop: 8 }}
        />
      </Modal>
    </div>
  );
}