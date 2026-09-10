// RAG 知识库问答系统 - 用户菜单（暗色模式 / 修改密码 / 退出）
import { useState } from 'react';
import { Dropdown, Modal, Input, message, Avatar } from 'antd';
import { UserOutlined, KeyOutlined, LogoutOutlined, BulbOutlined, BulbFilled } from '@ant-design/icons';
import { useAuthStore } from '../store/authStore';
import { authApi } from '../services/api';

export function UserMenu() {
  const { user, logout } = useAuthStore();
  const [open, setOpen] = useState(false);
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [loading, setLoading] = useState(false);

  const isDark = localStorage.getItem('theme') === 'dark';
  const toggleTheme = () => {
    const next = isDark ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    // 通知 App.tsx 切换主题（自定义事件）
    window.dispatchEvent(new CustomEvent('rag-theme-change', { detail: next }));
  };

  const handleChangePwd = async () => {
    if (!oldPwd || !newPwd) {
      message.warning('请填写完整');
      return;
    }
    setLoading(true);
    try {
      await authApi.changePassword(oldPwd, newPwd);
      message.success('密码修改成功');
      setOpen(false);
      setOldPwd('');
      setNewPwd('');
    } catch {
      message.error('密码修改失败，请检查旧密码');
    }
    setLoading(false);
  };

  if (!user) return null;

  const items = {
    items: [
      { key: 'user', label: `用户：${user.username}`, disabled: true },
      { type: 'divider' as const },
      {
        key: 'theme',
        icon: isDark ? <BulbFilled style={{ color: '#f59e0b' }} /> : <BulbOutlined />,
        label: isDark ? '切换到亮色模式' : '切换到暗色模式',
        onClick: () => {
          toggleTheme();
          message.success(isDark ? '已切换到亮色模式' : '已切换到暗色模式');
        },
      },
      {
        key: 'password',
        icon: <KeyOutlined />,
        label: '修改密码',
        onClick: () => setOpen(true),
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        danger: true,
        onClick: logout,
      },
    ],
  };

  return (
    <>
      <Dropdown menu={items} placement="bottomRight">
        <Avatar
          style={{
            cursor: 'pointer',
            background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
            boxShadow: '0 2px 8px rgba(99,102,241,0.35)',
          }}
          icon={<UserOutlined />}
        />
      </Dropdown>
      <Modal
        title="修改密码"
        open={open}
        onOk={handleChangePwd}
        onCancel={() => { setOpen(false); setOldPwd(''); setNewPwd(''); }}
        confirmLoading={loading}
        okText="确认修改"
        cancelText="取消"
      >
        <Input.Password
          placeholder="旧密码"
          value={oldPwd}
          onChange={(e) => setOldPwd(e.target.value)}
          style={{ marginBottom: 12 }}
        />
        <Input.Password
          placeholder="新密码（至少6位）"
          value={newPwd}
          onChange={(e) => setNewPwd(e.target.value)}
        />
      </Modal>
    </>
  );
}