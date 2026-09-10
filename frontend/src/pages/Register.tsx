// RAG 知识库问答系统 - 注册页面（现代渐变 + 玻璃拟态）
import { useState } from 'react';
import { Form, Input, Button, message } from 'antd';
import { UserOutlined, LockOutlined, ThunderboltFilled } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export default function Register() {
  const [loading, setLoading] = useState(false);
  const register = useAuthStore((s) => s.register);
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await register(values.username, values.password);
      message.success('注册成功，欢迎加入！');
      navigate('/chat', { replace: true });
    } catch (e: any) {
      message.error(e.response?.data?.detail || '注册失败，请重试');
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
            创建账号
          </h1>
          <div className="auth-subtitle">
            注册后即可开始智能问答
          </div>
        </div>

        <Form onFinish={onFinish} size="large" requiredMark={false}>
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, message: '用户名至少2个字符' },
              { max: 20, message: '用户名最多20个字符' },
            ]}
          >
            <Input
              prefix={<UserOutlined style={{ color: '#94a3b8' }} />}
              placeholder="用户名（2-20个字符）"
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码至少6位' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
              placeholder="密码（至少6位）"
              autoComplete="new-password"
            />
          </Form.Item>
          <Form.Item
            name="confirm"
            dependencies={['password']}
            rules={[
              { required: true, message: '请确认密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
              placeholder="确认密码"
              autoComplete="new-password"
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
              注 册
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center', fontSize: 13 }}>
          <span style={{ color: '#64748b' }}>已有账号？</span>
          <Link to="/login" style={{ color: '#6366f1', fontWeight: 600 }}>
            {' '}
            去登录
          </Link>
        </div>
      </div>
    </div>
  );
}