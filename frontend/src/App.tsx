// RAG 知识库问答系统 - 路由入口
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, theme, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState, useEffect } from 'react';
import { ProtectedRoute } from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import Chat from './pages/Chat';
import Dashboard from './pages/admin/Dashboard';

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark';
  });

  useEffect(() => {
    document.title = 'RAG 知识库问答系统';
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const saved = localStorage.getItem('theme');
    if (!saved) setDarkMode(mq.matches);
  }, []);

  // 监听 UserMenu 的暗色模式切换事件
  useEffect(() => {
    const handleThemeChange = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail === 'dark' || detail === 'light') {
        setDarkMode(detail === 'dark');
      }
    };
    window.addEventListener('rag-theme-change', handleThemeChange);
    return () => window.removeEventListener('rag-theme-change', handleThemeChange);
  }, []);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
      }}
    >
      <AntdApp>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <Chat />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute adminOnly>
                  <Dashboard />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

export default App;