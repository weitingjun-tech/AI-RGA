// RAG 知识库问答系统 - 审计日志（仅 Admin）
//
// 审计数据如果只能写不能看，等于没做——出事时没人能拿到线索。
// 这个页面回答的是：谁、在什么时候、对哪个对象、做了什么。
import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Select, Space, Typography, Tooltip, Input } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { adminApi } from '../../services/api';

const { Title, Text } = Typography;

interface AuditLog {
  id: number;
  username: string | null;
  action: string;
  target_type: string | null;
  target_id: number | null;
  detail: string | null;
  ip: string | null;
  request_id: string | null;
  status: string;
  created_at: string;
}

// 动作类型 -> 展示样式。没列出的动作按默认样式显示，
// 这样后端新增动作时前端不用同步改（接口有 /audit-logs/actions 提供实际取值）
const ACTION_STYLE: Record<string, { color: string; label: string }> = {
  'auth.login': { color: 'green', label: '登录成功' },
  'auth.login_failed': { color: 'red', label: '登录失败' },
  'auth.login_blocked': { color: 'volcano', label: '登录被锁定' },
  'auth.register': { color: 'blue', label: '注册' },
  'document.upload': { color: 'blue', label: '上传文档' },
  'document.delete': { color: 'red', label: '删除文档' },
  'document.reindex': { color: 'orange', label: '重新索引' },
  'knowledge_base.create': { color: 'blue', label: '创建知识库' },
  'knowledge_base.delete': { color: 'red', label: '删除知识库' },
  'knowledge_base.permission_grant': { color: 'purple', label: '授予权限' },
  'knowledge_base.permission_update': { color: 'purple', label: '变更权限' },
  'knowledge_base.permission_revoke': { color: 'orange', label: '撤销权限' },
};

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [actionFilter, setActionFilter] = useState<string | undefined>(undefined);
  const [usernameFilter, setUsernameFilter] = useState('');
  const [days, setDays] = useState(7);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.getAuditLogs({
        page,
        page_size: 20,
        action: actionFilter,
        username: usernameFilter || undefined,
        days,
      });
      setLogs(res.data.logs);
      setTotal(res.data.total);
    } finally {
      setLoading(false);
    }
  }, [page, actionFilter, usernameFilter, days]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    adminApi.getAuditActions().then((r) => setActions(r.data.actions || [])).catch(() => {});
  }, []);

  const columns: ColumnsType<AuditLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 165,
      render: (t: string) => (t ? new Date(t).toLocaleString() : '-'),
    },
    {
      title: '操作人',
      dataIndex: 'username',
      width: 110,
      render: (u: string | null) => u || <Text type="secondary">（未登录）</Text>,
    },
    {
      title: '动作',
      dataIndex: 'action',
      width: 130,
      render: (a: string) => {
        const s = ACTION_STYLE[a];
        return <Tag color={s?.color ?? 'default'}>{s?.label ?? a}</Tag>;
      },
    },
    {
      title: '对象',
      width: 150,
      render: (_: unknown, r) =>
        r.target_type ? `${r.target_type}#${r.target_id ?? '-'}` : '-',
    },
    {
      title: '详情',
      dataIndex: 'detail',
      ellipsis: true,
      render: (d: string | null) =>
        d ? (
          <Tooltip title={<pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{d}</pre>}>
            <Text style={{ fontSize: 12 }}>{d}</Text>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: '来源 IP',
      dataIndex: 'ip',
      width: 120,
      render: (v: string | null) => v || '-',
    },
    {
      title: '链路 ID',
      dataIndex: 'request_id',
      width: 130,
      render: (v: string | null) =>
        v ? (
          // 复制这个 id 去日志系统里搜，能还原这次请求的完整执行过程
          <Tooltip title="在服务端日志里搜索该 ID 可还原完整请求链路">
            <Text code style={{ fontSize: 11, cursor: 'pointer' }}>
              {v}
            </Text>
          </Tooltip>
        ) : (
          '-'
        ),
    },
  ];

  return (
    <Card style={{ borderRadius: 12 }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>📋 审计日志</Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          记录谁在什么时候对哪个对象做了什么，用于合规审计与事后追责
        </Text>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          style={{ width: 200 }}
          allowClear
          placeholder="全部动作类型"
          value={actionFilter}
          onChange={(v) => { setActionFilter(v); setPage(1); }}
          options={actions.map((a) => ({
            value: a,
            label: ACTION_STYLE[a]?.label ?? a,
          }))}
        />
        <Input.Search
          style={{ width: 180 }}
          placeholder="按用户名筛选"
          allowClear
          onSearch={(v) => { setUsernameFilter(v); setPage(1); }}
        />
        <Select
          style={{ width: 140 }}
          value={days}
          onChange={(v) => { setDays(v); setPage(1); }}
          options={[
            { value: 1, label: '最近 1 天' },
            { value: 7, label: '最近 7 天' },
            { value: 30, label: '最近 30 天' },
            { value: 365, label: '最近 1 年' },
          ]}
        />
      </Space>

      <Table
        columns={columns}
        dataSource={logs}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 条记录`,
        }}
      />
    </Card>
  );
}
