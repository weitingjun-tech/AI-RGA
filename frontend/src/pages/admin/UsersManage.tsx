// RAG 知识库问答系统 - 用户管理页面（仅 Admin）
import { useEffect, useState, useCallback } from 'react';
import { Table, Button, Popconfirm, Tag, Space, Card, Typography, message } from 'antd';
import { DeleteOutlined, UserOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { knowledgeApi } from '../../services/api';

const { Title, Text } = Typography;

interface UserRow {
  id: number;
  username: string;
  role: string;
  created_at: string | null;
}

export default function UsersManage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.getUsers();
      setUsers(res.data.users || []);
    } catch {
      message.error('获取用户列表失败');
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleDelete = async (id: number) => {
    try {
      await knowledgeApi.deleteUser(id);
      message.success('用户已删除');
      fetchUsers();
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败');
    }
  };

  const columns: ColumnsType<UserRow> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '用户名',
      dataIndex: 'username',
      render: (name: string) => (
        <Space>
          <UserOutlined style={{ color: '#6366f1' }} />
          {name}
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 110,
      render: (r: string) => (
        <Tag color={r === 'admin' ? 'purple' : 'blue'}>
          {r === 'admin' ? '管理员' : '普通用户'}
        </Tag>
      ),
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string | null) => (t ? new Date(t).toLocaleString() : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: any, record: UserRow) => (
        <Popconfirm
          title="确认删除该用户？其会话与消息也将被删除。"
          onConfirm={() => handleDelete(record.id)}
          okText="删除"
          cancelText="取消"
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={4} style={{ margin: 0 }}>👥 用户管理</Title>}
      extra={<Text type="secondary" style={{ fontSize: 12 }}>管理全部注册用户</Text>}
    >
      <Table
        columns={columns}
        dataSource={users}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 个用户` }}
      />
    </Card>
  );
}