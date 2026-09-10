// RAG 知识库问答系统 - 登录页面（现代渐变 + 玻璃拟态）
import { useState } from 'react';
import { Form, Input, Button, message } from 'antd';
import { UserOutlined, LockOutlined, ThunderboltFilled } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export default function Login() {
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(values.username, values.password);
      message.success('登录成功，欢迎回来！');
      navigate('/chat', { replace: true });
    } catch {
      message.error('用户名或密码错误');
    }
    setLoading(false);
  };

  return (
    <div className="auth-background">
      <div className="auth-grid-pattern" />
      <div className="auth-card">
        <div className="auth-logo-wrap">
          <div className="brand-logo">
            <ThunderboltFilled />
          </div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
            知识库问答系统
          </h1>
          <div className="auth-subtitle">
            基于 LangChain 的 RAG 企业级知识库 · 智能问答
          </div>
        </div>

        <Form onFinish={onFinish} size="large" requiredMark={false}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input
              prefix={<UserOutlined style={{ color: '#94a3b8' }} />}
              placeholder="用户名"
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password
              prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
              placeholder="密码"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginTop: 28, marginBottom: 16 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              size="large"
              loading={loading}
              className="btn-brand"
              style={{ height: 44, borderRadius: 12 }}
            >
              登 录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center', fontSize: 13 }}>
          <span style={{ color: '#64748b' }}>还没有账号？</span>
          <Link to="/register" style={{ color: '#6366f1', fontWeight: 600 }}>
            {' '}
            立即注册
          </Link>
        </div>
      </div>
    </div>
  );
}