// RAG 知识库问答系统 - 路由守卫
// 修复：刷新页面时 user 尚未加载，直接判断会误踢管理员。
// 现在：token 存在但 user 为空时，先自动 fetchUser，加载中显示 loading。
import { useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { useAuthStore } from '../store/authStore';

export function ProtectedRoute({ children, adminOnly = false }: {
  children: React.ReactNode;
  adminOnly?: boolean;
}) {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const fetchUser = useAuthStore((s) => s.fetchUser);

  useEffect(() => {
    if (token && !user) {
      fetchUser();
    }
  }, [token, user, fetchUser]);

  if (!token) return <Navigate to="/login" replace />;

  // 用户信息加载中（刷新页面后的初次获取）
  if (token && !user) {
    return (
      <div style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        background: '#f8fafc',
      }}>
        <Spin size="large" />
        <div style={{ color: '#64748b', fontSize: 13 }}>正在加载用户信息...</div>
      </div>
    );
  }

  if (adminOnly && user?.role !== 'admin') return <Navigate to="/chat" replace />;
  return <>{children}</>;
}