// RAG 知识库问答系统 - 管理后台 Dashboard（概览 / 知识库 / 用户）
import { useState, useEffect } from 'react';
import { Layout, Menu, Typography, Button, Space, Statistic, Row, Col, Card, Spin } from 'antd';
import { ArrowLeftOutlined, DashboardOutlined, DatabaseOutlined, TeamOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { UserMenu } from '../../components/UserMenu';
import KbManage from './KbManage';
import UsersManage from './UsersManage';
import { knowledgeApi } from '../../services/api';

const { Header, Sider, Content } = Layout;
const { Text, Title } = Typography;

type ViewKey = 'overview' | 'kb' | 'users';

export default function Dashboard() {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState<ViewKey>('overview');
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (view === 'overview') {
      knowledgeApi.getStats().then((res) => setStats(res.data)).catch(() => {});
    }
  }, [view]);

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: '系统概览' },
    { key: 'kb', icon: <DatabaseOutlined />, label: '知识库管理' },
    { key: 'users', icon: <TeamOutlined />, label: '用户管理' },
  ];

  const statCards = stats ? [
    { t: '文档总数', v: stats.documents ?? 0, s: '份' },
    { t: '已就绪文档', v: stats.ready_documents ?? 0, s: '份' },
    { t: '向量分块', v: stats.chunks ?? 0, s: '段' },
    { t: '注册用户', v: stats.users ?? 0, s: '人' },
    { t: '会话总数', v: stats.conversations ?? 0, s: '个' },
    { t: '对话消息', v: stats.messages ?? 0, s: '条' },
  ] : [];

  return (
    <Layout style={{ height: '100%' }}>
      <Header className="admin-header" style={{ height: 60 }}>
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/chat')} style={{ color: '#fff' }} />
          <Text style={{ color: '#fff', fontSize: 16, fontWeight: 600 }}>⚙️ 管理后台</Text>
        </Space>
        <UserMenu />
      </Header>
      <Layout>
        <Sider
          width={220}
          collapsedWidth={60}
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          style={{ background: '#fff' }}
        >
          <Menu
            mode="inline"
            selectedKeys={[view]}
            items={menuItems}
            onClick={({ key }) => setView(key as ViewKey)}
            style={{ borderRight: 0 }}
          />
        </Sider>
        <Content
          style={{
            padding: 24,
            background: 'linear-gradient(180deg,#f8fafc,#eef2ff)',
            overflow: 'auto',
            height: 'calc(100vh - 60px)',
          }}
        >
          {view === 'overview' && (
            <>
              <Card style={{ marginBottom: 16, borderRadius: 12 }}>
                <Title level={4} style={{ margin: 0 }}>📊 系统概览</Title>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  {user?.username}（管理员）· 系统整体运行情况
                </Text>
              </Card>
              {stats ? (
                <Row gutter={[16, 16]}>
                  {statCards.map((c) => (
                    <Col xs={12} sm={8} md={6} key={c.t}>
                      <Card
                        style={{
                          borderTop: '3px solid #6366f1',
                          borderRadius: 12,
                          boxShadow: '0 2px 8px rgba(99,102,241,0.08)',
                        }}
                      >
                        <Statistic title={c.t} value={c.v} suffix={c.s} />
                      </Card>
                    </Col>
                  ))}
                </Row>
              ) : (
                <div style={{ textAlign: 'center', padding: 80 }}>
                  <Spin size="large" />
                </div>
              )}
            </>
          )}
          {view === 'kb' && <KbManage />}
          {view === 'users' && <UsersManage />}
        </Content>
      </Layout>
    </Layout>
  );
}